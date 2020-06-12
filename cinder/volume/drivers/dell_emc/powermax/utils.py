# Copyright (c) 2017-2018 Dell Inc. or its subsidiaries.
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

from copy import deepcopy
import datetime
import hashlib
import re

from cinder.objects.group import Group
from oslo_log import log as logging
from oslo_utils import strutils
import six

from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder.volume import utils as vol_utils
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)
# SHARED CONSTANTS
ISCSI = 'iscsi'
FC = 'fc'
INTERVAL = 'interval'
RETRIES = 'retries'
VOLUME_ELEMENT_NAME_PREFIX = 'OS-'
VMAX_AFA_MODELS = ['VMAX250F', 'VMAX450F', 'VMAX850F', 'VMAX950F']
MAX_SRP_LENGTH = 16
TRUNCATE_5 = 5
TRUNCATE_27 = 27

ARRAY = 'array'
SLO = 'slo'
WORKLOAD = 'workload'
SRP = 'srp'
PORTGROUPNAME = 'storagetype:portgroupname'
DEVICE_ID = 'device_id'
INITIATOR_CHECK = 'initiator_check'
SG_NAME = 'storagegroup_name'
MV_NAME = 'maskingview_name'
IG_NAME = 'init_group_name'
PARENT_SG_NAME = 'parent_sg_name'
CONNECTOR = 'connector'
VOL_NAME = 'volume_name'
EXTRA_SPECS = 'extra_specs'
HOST_NAME = 'short_host_name'
IS_RE = 'replication_enabled'
DISABLECOMPRESSION = 'storagetype:disablecompression'
REP_SYNC = 'Synchronous'
REP_ASYNC = 'Asynchronous'
REP_METRO = 'Metro'
REP_MODE = 'rep_mode'
RDF_SYNC_STATE = 'synchronized'
RDF_SYNCINPROG_STATE = 'syncinprog'
RDF_CONSISTENT_STATE = 'consistent'
RDF_SUSPENDED_STATE = 'suspended'
RDF_FAILEDOVER_STATE = 'failed over'
RDF_ACTIVE = 'active'
RDF_ACTIVEACTIVE = 'activeactive'
RDF_ACTIVEBIAS = 'activebias'
RDF_CONS_EXEMPT = 'consExempt'
METROBIAS = 'metro_bias'
DEFAULT_PORT = 8443
CLONE_SNAPSHOT_NAME = "snapshot_for_clone"

# Multiattach constants
IS_MULTIATTACH = 'multiattach'
OTHER_PARENT_SG = 'other_parent_sg_name'
FAST_SG = 'fast_managed_sg'
NO_SLO_SG = 'no_slo_sg'

# SG for unmanaged volumes
UNMANAGED_SG = 'OS-Unmanaged'

# Cinder.conf vmax configuration
VMAX_SERVER_IP = 'san_ip'
VMAX_USER_NAME = 'san_login'
VMAX_PASSWORD = 'san_password'
VMAX_SERVER_PORT_NEW = 'san_api_port'
VMAX_SERVER_PORT_OLD = 'san_rest_port'
VMAX_ARRAY = 'vmax_array'
VMAX_WORKLOAD = 'vmax_workload'
VMAX_SRP = 'vmax_srp'
VMAX_SERVICE_LEVEL = 'vmax_service_level'
VMAX_PORT_GROUPS = 'vmax_port_groups'
VMAX_SNAPVX_UNLINK_LIMIT = 'vmax_snapvx_unlink_limit'
U4P_FAILOVER_TIMEOUT = 'u4p_failover_timeout'
U4P_FAILOVER_RETRIES = 'u4p_failover_retries'
U4P_FAILOVER_BACKOFF_FACTOR = 'u4p_failover_backoff_factor'
U4P_FAILOVER_AUTOFAILBACK = 'u4p_failover_autofailback'
U4P_FAILOVER_TARGETS = 'u4p_failover_target'
POWERMAX_ARRAY = 'powermax_array'
POWERMAX_SRP = 'powermax_srp'
POWERMAX_SERVICE_LEVEL = 'powermax_service_level'
POWERMAX_PORT_GROUPS = 'powermax_port_groups'
POWERMAX_SNAPVX_UNLINK_LIMIT = 'powermax_snapvx_unlink_limit'


class PowerMaxUtils(object):
    """Utility class for Rest based PowerMax volume drivers.

    This Utility class is for PowerMax volume drivers based on Unisphere
    Rest API.
    """

    def __init__(self):
        """Utility class for Rest based PowerMax volume drivers."""

    def get_host_short_name(self, host_name):
        """Returns the short name for a given qualified host name.

        Checks the host name to see if it is the fully qualified host name
        and returns part before the dot. If there is no dot in the host name
        the full host name is returned.
        :param host_name: the fully qualified host name
        :returns: string -- the short host_name
        """
        host_array = host_name.split('.')
        if len(host_array) > 1:
            short_host_name = host_array[0]
        else:
            short_host_name = host_name

        return self.generate_unique_trunc_host(short_host_name)

    @staticmethod
    def get_volumetype_extra_specs(volume, volume_type_id=None):
        """Gets the extra specs associated with a volume type.

        :param volume: the volume dictionary
        :param volume_type_id: Optional override for volume.volume_type_id
        :returns: dict -- extra_specs - the extra specs
        :raises: VolumeBackendAPIException
        """
        extra_specs = {}

        try:
            if volume_type_id:
                type_id = volume_type_id
            else:
                type_id = volume.volume_type_id
            if type_id is not None:
                extra_specs = volume_types.get_volume_type_extra_specs(type_id)
        except Exception as e:
            LOG.debug('Exception getting volume type extra specs: %(e)s',
                      {'e': six.text_type(e)})
        return extra_specs

    @staticmethod
    def get_short_protocol_type(protocol):
        """Given the protocol type, return I for iscsi and F for fc.

        :param protocol: iscsi or fc
        :returns: string -- 'I' for iscsi or 'F' for fc
        """
        if protocol.lower() == ISCSI.lower():
            return 'I'
        elif protocol.lower() == FC.lower():
            return 'F'
        else:
            return protocol

    @staticmethod
    def truncate_string(str_to_truncate, max_num):
        """Truncate a string by taking first and last characters.

        :param str_to_truncate: the string to be truncated
        :param max_num: the maximum number of characters
        :returns: string -- truncated string or original string
        """
        if len(str_to_truncate) > max_num:
            new_num = len(str_to_truncate) - max_num // 2
            first_chars = str_to_truncate[:max_num // 2]
            last_chars = str_to_truncate[new_num:]
            str_to_truncate = first_chars + last_chars
        return str_to_truncate

    @staticmethod
    def get_time_delta(start_time, end_time):
        """Get the delta between start and end time.

        :param start_time: the start time
        :param end_time: the end time
        :returns: string -- delta in string H:MM:SS
        """
        delta = end_time - start_time
        return six.text_type(datetime.timedelta(seconds=int(delta)))

    def get_default_storage_group_name(
            self, srp_name, slo, workload, is_compression_disabled=False,
            is_re=False, rep_mode=None):
        """Determine default storage group from extra_specs.

        :param srp_name: the name of the srp on the array
        :param slo: the service level string e.g Bronze
        :param workload: the workload string e.g DSS
        :param is_compression_disabled:  flag for disabling compression
        :param is_re: flag for replication
        :param rep_mode: flag to indicate replication mode
        :returns: storage_group_name
        """
        if slo and workload:
            prefix = ("OS-%(srpName)s-%(slo)s-%(workload)s"
                      % {'srpName': srp_name, 'slo': slo,
                         'workload': workload})

            if is_compression_disabled:
                prefix += "-CD"

        else:
            prefix = "OS-no_SLO"
        if is_re:
            prefix += self.get_replication_prefix(rep_mode)

        storage_group_name = ("%(prefix)s-SG" % {'prefix': prefix})
        return storage_group_name

    @staticmethod
    def get_volume_element_name(volume_id):
        """Get volume element name follows naming convention, i.e. 'OS-UUID'.

        :param volume_id: Openstack volume ID containing uuid
        :returns: volume element name in format of OS-UUID
        """
        element_name = volume_id
        uuid_regex = (re.compile(
            r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',
            re.I))
        match = uuid_regex.search(volume_id)
        if match:
            volume_uuid = match.group()
            element_name = ("%(prefix)s%(volumeUUID)s"
                            % {'prefix': VOLUME_ELEMENT_NAME_PREFIX,
                               'volumeUUID': volume_uuid})
            LOG.debug(
                "get_volume_element_name elementName:  %(elementName)s.",
                {'elementName': element_name})
        return element_name

    @staticmethod
    def modify_snapshot_prefix(snapshot_name, manage=False, unmanage=False):
        """Modify a Snapshot prefix on PowerMax/VMAX backend.

        Prepare a snapshot name for manage/unmanage snapshot process either
        by adding or removing 'OS-' prefix.

        :param snapshot_name: the old snapshot backend display name
        :param manage: (bool) if the operation is managing a snapshot
        :param unmanage: (bool) if the operation is unmanaging a snapshot
        :return: snapshot name ready for backend PowerMax/VMAX assignment
        """
        new_snap_name = None
        if manage:
            new_snap_name = ("%(prefix)s%(snapshot_name)s"
                             % {'prefix': 'OS-',
                                'snapshot_name': snapshot_name})

        if unmanage:
            snap_split = snapshot_name.split("-", 1)
            if snap_split[0] == 'OS':
                new_snap_name = snap_split[1]

        return new_snap_name

    def generate_unique_trunc_host(self, host_name):
        """Create a unique short host name under 16 characters.

        :param host_name: long host name
        :returns: truncated host name
        """
        if host_name and len(host_name) > 16:
            host_name = host_name.lower()
            m = hashlib.md5()
            m.update(host_name.encode('utf-8'))
            uuid = m.hexdigest()
            new_name = ("%(host)s%(uuid)s"
                        % {'host': host_name[-6:],
                           'uuid': uuid})
            host_name = self.truncate_string(new_name, 16)
        return host_name

    def get_pg_short_name(self, portgroup_name):
        """Create a unique port group name under 12 characters.

        :param portgroup_name: long portgroup_name
        :returns: truncated portgroup_name
        """
        if portgroup_name and len(portgroup_name) > 12:
            portgroup_name = portgroup_name.lower()
            m = hashlib.md5()
            m.update(portgroup_name.encode('utf-8'))
            uuid = m.hexdigest()
            new_name = ("%(pg)s%(uuid)s"
                        % {'pg': portgroup_name[-6:],
                           'uuid': uuid})
            portgroup_name = self.truncate_string(new_name, 12)
        return portgroup_name

    @staticmethod
    def get_default_oversubscription_ratio(max_over_sub_ratio):
        """Override ratio if necessary.

        The over subscription ratio will be overridden if the user supplied
        max oversubscription ratio is less than 1.
        :param max_over_sub_ratio: user supplied over subscription ratio
        :returns: max_over_sub_ratio
        """
        if max_over_sub_ratio < 1.0:
            LOG.info("The user supplied value for max_over_subscription "
                     "ratio is less than 1.0. Using the default value of "
                     "20.0 instead...")
            max_over_sub_ratio = 20.0
        return max_over_sub_ratio

    def get_temp_snap_name(self, source_device_id):
        """Construct a temporary snapshot name for clone operation

        :param source_device_id: the source device id
        :return: snap_name
        """
        snap_name = ("temp-%(device)s-%(snap_name)s"
                     % {'device': source_device_id,
                        'snap_name': CLONE_SNAPSHOT_NAME})
        return snap_name

    @staticmethod
    def get_array_and_device_id(volume, external_ref):
        """Helper function for manage volume to get array name and device ID.

        :param volume: volume object from API
        :param external_ref: the existing volume object to be manged
        :returns: string value of the array name and device ID
        """
        device_id = external_ref.get(u'source-name', None)
        LOG.debug("External_ref: %(er)s", {'er': external_ref})
        if not device_id:
            device_id = external_ref.get(u'source-id', None)
        host = volume.host
        host_list = host.split('+')
        array = host_list[(len(host_list) - 1)]

        if device_id:
            if len(device_id) != 5:
                error_message = (_("Device ID: %(device_id)s is invalid. "
                                   "Device ID should be exactly 5 digits.") %
                                 {'device_id': device_id})
                LOG.error(error_message)
                raise exception.VolumeBackendAPIException(
                    message=error_message)
            LOG.debug("Get device ID of existing volume - device ID: "
                      "%(device_id)s, Array: %(array)s.",
                      {'device_id': device_id,
                       'array': array})
        else:
            exception_message = (_("Source volume device ID is required."))
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        return array, device_id.upper()

    @staticmethod
    def is_compression_disabled(extra_specs):
        """Check is compression is to be disabled.

        :param extra_specs: extra specifications
        :returns: boolean
        """
        do_disable_compression = False
        if DISABLECOMPRESSION in extra_specs:
            if strutils.bool_from_string(extra_specs[DISABLECOMPRESSION]):
                do_disable_compression = True
        return do_disable_compression

    def change_compression_type(self, is_source_compr_disabled, new_type):
        """Check if volume type have different compression types

        :param is_source_compr_disabled: from source
        :param new_type: from target
        :returns: boolean
        """
        extra_specs = new_type['extra_specs']
        is_target_compr_disabled = self.is_compression_disabled(extra_specs)
        if is_target_compr_disabled == is_source_compr_disabled:
            return False
        else:
            return True

    def change_replication(self, vol_is_replicated, new_type):
        """Check if volume types have different replication status.

        :param vol_is_replicated: from source
        :param new_type: from target
        :return: bool
        """
        is_tgt_rep = self.is_replication_enabled(new_type['extra_specs'])
        return vol_is_replicated != is_tgt_rep

    @staticmethod
    def is_replication_enabled(extra_specs):
        """Check if replication is to be enabled.

        :param extra_specs: extra specifications
        :returns: bool - true if enabled, else false
        """
        replication_enabled = False
        if IS_RE in extra_specs:
            replication_enabled = True
        return replication_enabled

    @staticmethod
    def get_replication_config(rep_device_list):
        """Gather necessary replication configuration info.

        :param rep_device_list: the replication device list from cinder.conf
        :returns: rep_config, replication configuration dict
        """
        rep_config = {}
        if not rep_device_list:
            return None
        else:
            target = rep_device_list[0]
            try:
                rep_config['array'] = target['target_device_id']
                rep_config['srp'] = target['remote_pool']
                rep_config['rdf_group_label'] = target['rdf_group_label']
                rep_config['portgroup'] = target['remote_port_group']

            except KeyError as ke:
                error_message = (_("Failed to retrieve all necessary SRDF "
                                   "information. Error received: %(ke)s.") %
                                 {'ke': six.text_type(ke)})
                LOG.exception(error_message)
                raise exception.VolumeBackendAPIException(
                    message=error_message)

            allow_extend = target.get('allow_extend', 'false')
            if strutils.bool_from_string(allow_extend):
                rep_config['allow_extend'] = True
            else:
                rep_config['allow_extend'] = False

            rep_mode = target.get('mode', '')
            if rep_mode.lower() in ['async', 'asynchronous']:
                rep_config['mode'] = REP_ASYNC
            elif rep_mode.lower() == 'metro':
                rep_config['mode'] = REP_METRO
                metro_bias = target.get('metro_use_bias', 'false')
                if strutils.bool_from_string(metro_bias):
                    rep_config[METROBIAS] = True
                else:
                    rep_config[METROBIAS] = False
                allow_delete_metro = target.get('allow_delete_metro', 'false')
                if strutils.bool_from_string(allow_delete_metro):
                    rep_config['allow_delete_metro'] = True
                else:
                    rep_config['allow_delete_metro'] = False
            else:
                rep_config['mode'] = REP_SYNC

        return rep_config

    @staticmethod
    def is_volume_failed_over(volume):
        """Check if a volume has been failed over.

        :param volume: the volume object
        :returns: bool
        """
        if volume is not None:
            if volume.get('replication_status') and (
                volume.replication_status ==
                    fields.ReplicationStatus.FAILED_OVER):
                    return True
        return False

    @staticmethod
    def update_volume_model_updates(volume_model_updates,
                                    volumes, group_id, status='available'):
        """Update the volume model's status and return it.

        :param volume_model_updates: list of volume model update dicts
        :param volumes: volumes object api
        :param group_id: consistency group id
        :param status: string value reflects the status of the member volume
        :returns: volume_model_updates - updated volumes
        """
        LOG.info("Updating status for group: %(id)s.", {'id': group_id})
        if volumes:
            for volume in volumes:
                volume_model_updates.append({'id': volume.id,
                                             'status': status})
        else:
            LOG.info("No volume found for group: %(cg)s.", {'cg': group_id})
        return volume_model_updates

    @staticmethod
    def get_grp_volume_model_update(volume, volume_dict, group_id):
        """Create and return the volume model update on creation.

        :param volume: volume object
        :param volume_dict: the volume dict
        :param group_id: consistency group id
        :returns: model_update
        """
        LOG.info("Updating status for group: %(id)s.", {'id': group_id})
        model_update = ({'id': volume.id, 'status': 'available',
                         'provider_location': six.text_type(volume_dict)})
        return model_update

    @staticmethod
    def update_extra_specs(extraspecs):
        """Update extra specs.

        :param extraspecs: the additional info
        :returns: extraspecs
        """
        try:
            pool_details = extraspecs['pool_name'].split('+')
            extraspecs[SLO] = pool_details[0]
            if len(pool_details) == 4:
                extraspecs[WORKLOAD] = pool_details[1]
                extraspecs[SRP] = pool_details[2]
                extraspecs[ARRAY] = pool_details[3]
            else:
                # Assume no workload given in pool name
                extraspecs[SRP] = pool_details[1]
                extraspecs[ARRAY] = pool_details[2]
                extraspecs[WORKLOAD] = 'NONE'
        except KeyError:
            LOG.error("Error parsing SLO, workload from"
                      " the provided extra_specs.")
        return extraspecs

    def get_volume_group_utils(self, group, interval, retries):
        """Standard utility for generic volume groups.

        :param group: the generic volume group object to be created
        :param interval: Interval in seconds between retries
        :param retries: Retry count
        :returns: array, intervals_retries_dict
        :raises: VolumeBackendAPIException
        """
        arrays = set()
        # Check if it is a generic volume group instance
        if isinstance(group, Group):
            for volume_type in group.volume_types:
                extra_specs = self.update_extra_specs(volume_type.extra_specs)
                arrays.add(extra_specs[ARRAY])
        else:
            msg = (_("Unable to get volume type ids."))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(message=msg)

        if len(arrays) != 1:
            if not arrays:
                msg = (_("Failed to get an array associated with "
                         "volume group: %(groupid)s.")
                       % {'groupid': group.id})
            else:
                msg = (_("There are multiple arrays "
                         "associated with volume group: %(groupid)s.")
                       % {'groupid': group.id})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(message=msg)
        array = arrays.pop()
        intervals_retries_dict = {INTERVAL: interval, RETRIES: retries}
        return array, intervals_retries_dict

    def update_volume_group_name(self, group):
        """Format id and name consistency group.

        :param group: the generic volume group object
        :returns: group_name -- formatted name + id
        """
        group_name = ""
        if group.name is not None and group.name != group.id:
            group_name = (
                self.truncate_string(
                    group.name, TRUNCATE_27) + "_")

        group_name += group.id
        return group_name

    @staticmethod
    def add_legacy_pools(pools):
        """Add legacy pools to allow extending a volume after upgrade.

        :param pools: the pool list
        :return: pools - the updated pool list
        """
        extra_pools = []
        for pool in pools:
            if 'none' in pool['pool_name'].lower():
                extra_pools.append(pool)
        for pool in extra_pools:
            try:
                slo = pool['pool_name'].split('+')[0]
                srp = pool['pool_name'].split('+')[2]
                array = pool['pool_name'].split('+')[3]
            except IndexError:
                slo = pool['pool_name'].split('+')[0]
                srp = pool['pool_name'].split('+')[1]
                array = pool['pool_name'].split('+')[2]
            new_pool_name = ('%(slo)s+%(srp)s+%(array)s'
                             % {'slo': slo, 'srp': srp, 'array': array})
            new_pool = deepcopy(pool)
            new_pool['pool_name'] = new_pool_name
            pools.append(new_pool)
        return pools

    def check_replication_matched(self, volume, extra_specs):
        """Check volume type and group type.

        This will make sure they do not conflict with each other.

        :param volume: volume to be checked
        :param extra_specs: the extra specifications
        :raises: InvalidInput
        """
        # If volume is not a member of group, skip this check anyway.
        if not volume.group:
            return
        vol_is_re = self.is_replication_enabled(extra_specs)
        group_is_re = volume.group.is_replicated

        if not (vol_is_re == group_is_re):
            msg = _('Replication should be enabled or disabled for both '
                    'volume or group. Volume replication status: '
                    '%(vol_status)s, group replication status: '
                    '%(group_status)s') % {
                        'vol_status': vol_is_re, 'group_status': group_is_re}
            raise exception.InvalidInput(reason=msg)

    @staticmethod
    def check_rep_status_enabled(group):
        """Check replication status for group.

        Group status must be enabled before proceeding with certain
        operations.

        :param group: the group object
        :raises: InvalidInput
        """
        if group.is_replicated:
            if group.replication_status != fields.ReplicationStatus.ENABLED:
                msg = (_('Replication status should be %s for '
                         'replication-enabled group.')
                       % fields.ReplicationStatus.ENABLED)
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)
        else:
            LOG.debug('Replication is not enabled on group %s, '
                      'skip status check.', group.id)

    @staticmethod
    def get_replication_prefix(rep_mode):
        """Get the replication prefix.

        Replication prefix for storage group naming is based on whether it is
        synchronous, asynchronous, or metro replication mode.

        :param rep_mode: flag to indicate if replication is async
        :return: prefix
        """
        if rep_mode == REP_ASYNC:
            prefix = "-RA"
        elif rep_mode == REP_METRO:
            prefix = "-RM"
        else:
            prefix = "-RE"
        return prefix

    @staticmethod
    def get_async_rdf_managed_grp_name(rep_config):
        """Get the name of the group used for async replication management.

        :param rep_config: the replication configuration
        :return: group name
        """
        async_grp_name = ("OS-%(rdf)s-%(mode)s-rdf-sg"
                          % {'rdf': rep_config['rdf_group_label'],
                             'mode': rep_config['mode']})
        LOG.debug("The async/ metro rdf managed group name is %(name)s",
                  {'name': async_grp_name})
        return async_grp_name

    def is_metro_device(self, rep_config, extra_specs):
        """Determine if a volume is a Metro enabled device.

        :param rep_config: the replication configuration
        :param extra_specs: the extra specifications
        :return: bool
        """
        is_metro = (True if self.is_replication_enabled(extra_specs)
                    and rep_config is not None
                    and rep_config['mode'] == REP_METRO else False)
        return is_metro

    def does_vol_need_rdf_management_group(self, extra_specs):
        """Determine if a volume is a Metro or Async.

        :param extra_specs: the extra specifications
        :return: bool
        """
        if (self.is_replication_enabled(extra_specs) and
                extra_specs.get(REP_MODE, None) in
                [REP_ASYNC, REP_METRO]):
            return True
        return False

    def derive_default_sg_from_extra_specs(self, extra_specs, rep_mode=None):
        """Get the name of the default sg from the extra specs.

        :param extra_specs: extra specs
        :returns: default sg - string
        """
        do_disable_compression = self.is_compression_disabled(
            extra_specs)
        rep_enabled = self.is_replication_enabled(extra_specs)
        return self.get_default_storage_group_name(
            extra_specs[SRP], extra_specs[SLO],
            extra_specs[WORKLOAD],
            is_compression_disabled=do_disable_compression,
            is_re=rep_enabled, rep_mode=rep_mode)

    @staticmethod
    def merge_dicts(d1, *args):
        """Merge dictionaries

        :param d1: dict 1
        :param *args: one or more dicts
        :returns: merged dict
        """
        d2 = {}
        for d in args:
            d2 = d.copy()
            d2.update(d1)
            d1 = d2
        return d2

    @staticmethod
    def get_temp_failover_grp_name(rep_config):
        """Get the temporary group name used for failover.

        :param rep_config: the replication config
        :return: temp_grp_name
        """
        temp_grp_name = ("OS-%(rdf)s-temp-rdf-sg"
                         % {'rdf': rep_config['rdf_group_label']})
        LOG.debug("The temp rdf managed group name is %(name)s",
                  {'name': temp_grp_name})
        return temp_grp_name

    def get_child_sg_name(self, host_name, extra_specs):
        """Get the child storage group name for a masking view.

        :param host_name: the short host name
        :param extra_specs: the extra specifications
        :return: child sg name, compression flag, rep flag, short pg name
        """
        do_disable_compression = False
        pg_name = self.get_pg_short_name(extra_specs[PORTGROUPNAME])
        rep_enabled = self.is_replication_enabled(extra_specs)
        if extra_specs[SLO]:
            slo_wl_combo = self.truncate_string(
                extra_specs[SLO] + extra_specs[WORKLOAD], 10)
            unique_name = self.truncate_string(extra_specs[SRP], 12)
            child_sg_name = (
                "OS-%(shortHostName)s-%(srpName)s-%(combo)s-%(pg)s"
                % {'shortHostName': host_name,
                   'srpName': unique_name,
                   'combo': slo_wl_combo,
                   'pg': pg_name})
            do_disable_compression = self.is_compression_disabled(
                extra_specs)
            if do_disable_compression:
                child_sg_name = ("%(child_sg_name)s-CD"
                                 % {'child_sg_name': child_sg_name})
        else:
            child_sg_name = (
                "OS-%(shortHostName)s-No_SLO-%(pg)s"
                % {'shortHostName': host_name, 'pg': pg_name})
        if rep_enabled:
            rep_mode = extra_specs.get(REP_MODE, None)
            child_sg_name += self.get_replication_prefix(rep_mode)
        return child_sg_name, do_disable_compression, rep_enabled, pg_name

    @staticmethod
    def change_multiattach(extra_specs, new_type_extra_specs):
        """Check if a change in multiattach is required for retype.

        :param extra_specs: the source type extra specs
        :param new_type_extra_specs: the target type extra specs
        :return: bool
        """
        is_src_multiattach = vol_utils.is_boolean_str(
            extra_specs.get('multiattach'))
        is_tgt_multiattach = vol_utils.is_boolean_str(
            new_type_extra_specs.get('multiattach'))
        return is_src_multiattach != is_tgt_multiattach

    @staticmethod
    def is_volume_manageable(source_vol):
        """Check if a volume with verbose description is valid for management.

        :param source_vol: the verbose volume dict
        :return: bool True/False
        """
        vol_head = source_vol['volumeHeader']

        # PowerMax/VMAX disk geometry uses cylinders, so volume sizes are
        # matched to the nearest full cylinder size: 1GB = 547cyl = 1026MB
        if vol_head['capMB'] < 1026 or not vol_head['capGB'].is_integer():
            return False

        if (vol_head['numSymDevMaskingViews'] > 0 or
                vol_head['mapped'] is True or
                source_vol['maskingInfo']['masked'] is True):
            return False

        if (vol_head['status'] != 'Ready' or
                vol_head['serviceState'] != 'Normal' or
                vol_head['emulationType'] != 'FBA' or
                vol_head['configuration'] != 'TDEV' or
                vol_head['system_resource'] is True or
                vol_head['private'] is True or
                vol_head['encapsulated'] is True or
                vol_head['reservationInfo']['reserved'] is True):
            return False

        for key, value in source_vol['rdfInfo'].items():
            if value is True:
                return False

        if source_vol['timeFinderInfo']['snapVXTgt'] is True:
            return False

        if vol_head['nameModifier'][0:3] == 'OS-':
            return False

        return True

    @staticmethod
    def is_snapshot_manageable(source_vol):
        """Check if a volume with snapshot description is valid for management.

        :param source_vol: the verbose volume dict
        :return: bool True/False
        """
        vol_head = source_vol['volumeHeader']

        if not source_vol['timeFinderInfo']['snapVXSrc']:
            return False

        # PowerMax/VMAX disk geometry uses cylinders, so volume sizes are
        # matched to the nearest full cylinder size: 1GB = 547cyl = 1026MB
        if (vol_head['capMB'] < 1026 or
                not vol_head['capGB'].is_integer()):
            return False

        if (vol_head['emulationType'] != 'FBA' or
                vol_head['configuration'] != 'TDEV' or
                vol_head['private'] is True or
                vol_head['system_resource'] is True):
            return False

        snap_gen_info = (source_vol['timeFinderInfo']['snapVXSession'][0][
            'srcSnapshotGenInfo'][0]['snapshotHeader'])

        if (snap_gen_info['snapshotName'][0:3] == 'OS-' or
                snap_gen_info['snapshotName'][0:5] == 'temp-'):
            return False

        if (snap_gen_info['expired'] is True
                or snap_gen_info['generation'] > 0):
            return False

        return True

    @staticmethod
    def get_volume_attached_hostname(device_info):
        """Parse a hostname from a storage group ID.

        :param device_info: the device info dict
        :return: str -- the attached hostname
        """
        try:
            sg_id = device_info.get("storageGroupId")[0]
            return sg_id.split('-')[1]
        except IndexError:
            return None

    def get_object_components_and_correct_host(self, regex_str, input_str):
        """Get components from input string.

        :param regex_str: the regex -- str
        :param input_str: the input string -- str
        :returns: object components -- dict
        """
        object_dict = self.get_object_components(regex_str, input_str)
        if object_dict and 'host' in object_dict:
            if object_dict['host'].endswith('-'):
                object_dict['host'] = object_dict['host'][:-1]
        return object_dict

    @staticmethod
    def get_object_components(regex_str, input_str):
        """Get components from input string.

        :param regex_str: the regex -- str
        :param input_str: the input string -- str
        :returns: dict
        """
        full_str = re.compile(regex_str)
        match = full_str.match(input_str)
        return match.groupdict() if match else None
