# Copyright (c) 2020 Dell Inc. or its subsidiaries.
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
import re

from oslo_log import log as logging
from oslo_utils.secretutils import md5
from oslo_utils import strutils
from oslo_utils import units
import packaging.version
import six

from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder.objects.group import Group
from cinder.volume import volume_types
from cinder.volume import volume_utils


LOG = logging.getLogger(__name__)
# SHARED CONSTANTS
ISCSI = 'iscsi'
FC = 'fc'
INTERVAL = 'interval'
RETRIES = 'retries'
VOLUME_ELEMENT_NAME_PREFIX = 'OS-'
MAX_SRP_LENGTH = 16
TRUNCATE_5 = 5
TRUNCATE_27 = 27
UCODE_5978_ELMSR = 221
UCODE_5978_HICKORY = 660
UCODE_5978 = 5978
UPPER_HOST_CHARS = 16
UPPER_PORT_GROUP_CHARS = 12

ARRAY = 'array'
REMOTE_ARRAY = 'remote_array'
SLO = 'slo'
WORKLOAD = 'workload'
SRP = 'srp'
PORTGROUPNAME = 'storagetype:portgroupname'
DEVICE_ID = 'device_id'
INITIATOR_CHECK = 'initiator_check'
SG_NAME = 'storagegroup_name'
SG_ID = 'storageGroupId'
MV_NAME = 'maskingview_name'
IG_NAME = 'init_group_name'
PARENT_SG_NAME = 'parent_sg_name'
CONNECTOR = 'connector'
VOL_NAME = 'volume_name'
EXTRA_SPECS = 'extra_specs'
HOST_NAME = 'short_host_name'
IS_RE = 'replication_enabled'
IS_RE_CAMEL = 'ReplicationEnabled'
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
RDF_PARTITIONED_STATE = 'partitioned'
RDF_TRANSIDLE_STATE = 'transidle'
RDF_PAIR_STATE = 'rdfpairState'
RDF_VALID_STATES_SYNC = [RDF_SYNC_STATE, RDF_SUSPENDED_STATE,
                         RDF_SYNCINPROG_STATE]
RDF_VALID_STATES_ASYNC = [RDF_CONSISTENT_STATE, RDF_SUSPENDED_STATE,
                          RDF_SYNCINPROG_STATE]
RDF_VALID_STATES_METRO = [RDF_ACTIVEBIAS, RDF_ACTIVEACTIVE,
                          RDF_SUSPENDED_STATE, RDF_SYNCINPROG_STATE]
RDF_PARTITIONED_STATES = [RDF_PARTITIONED_STATE, RDF_TRANSIDLE_STATE]
RDF_CONS_EXEMPT = 'exempt'
RDF_ALLOW_METRO_DELETE = 'allow_delete_metro'
RDF_GROUP_NO = 'rdf_group_number'
METROBIAS = 'metro_bias'
BACKEND_ID = 'backend_id'
BACKEND_ID_LEGACY_REP = 'backend_id_legacy_rep'
REPLICATION_DEVICE_BACKEND_ID = 'storagetype:replication_device_backend_id'
REP_CONFIG = 'rep_config'
DEFAULT_PORT = 8443
CLONE_SNAPSHOT_NAME = "snapshot_for_clone"
STORAGE_GROUP_TAGS = 'storagetype:storagegrouptags'
TAG_LIST = 'tag_list'
USED_HOST_NAME = "used_host_name"
RDF_SYNCED_STATES = [RDF_SYNC_STATE, RDF_CONSISTENT_STATE,
                     RDF_ACTIVEACTIVE, RDF_ACTIVEBIAS]
FORCE_VOL_EDIT = 'force_vol_edit'
PMAX_FAILOVER_START_ARRAY_PROMOTION = 'pmax_failover_start_array_promotion'

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
U4P_SERVER_PORT = 'san_api_port'
VMAX_WORKLOAD = 'vmax_workload'
U4P_FAILOVER_TIMEOUT = 'u4p_failover_timeout'
U4P_FAILOVER_RETRIES = 'u4p_failover_retries'
U4P_FAILOVER_BACKOFF_FACTOR = 'u4p_failover_backoff_factor'
U4P_FAILOVER_AUTOFAILBACK = 'u4p_failover_autofailback'
U4P_FAILOVER_TARGETS = 'u4p_failover_target'
POWERMAX_ARRAY = 'powermax_array'
POWERMAX_SRP = 'powermax_srp'
POWERMAX_SERVICE_LEVEL = 'powermax_service_level'
POWERMAX_PORT_GROUPS = 'powermax_port_groups'
POWERMAX_ARRAY_TAG_LIST = 'powermax_array_tag_list'
POWERMAX_SHORT_HOST_NAME_TEMPLATE = 'powermax_short_host_name_template'
POWERMAX_PORT_GROUP_NAME_TEMPLATE = 'powermax_port_group_name_template'
PORT_GROUP_LABEL = 'port_group_label'

# Array Models, Service Levels & Workloads
VMAX_HYBRID_MODELS = ['VMAX100K', 'VMAX200K', 'VMAX400K']
VMAX_AFA_MODELS = ['VMAX250F', 'VMAX450F', 'VMAX850F', 'VMAX950F']
PMAX_MODELS = ['PowerMax_2000', 'PowerMax_8000']

HYBRID_SLS = ['Diamond', 'Platinum', 'Gold', 'Silver', 'Bronze', 'Optimized',
              'None', 'NONE']
HYBRID_WLS = ['OLTP', 'OLTP_REP', 'DSS', 'DSS_REP', 'NONE', 'None']
AFA_H_SLS = ['Diamond', 'Optimized', 'None', 'NONE']
AFA_P_SLS = ['Diamond', 'Platinum', 'Gold', 'Silver', 'Bronze', 'Optimized',
             'None', 'NONE']
AFA_WLS = ['OLTP', 'OLTP_REP', 'DSS', 'DSS_REP', 'NONE', 'None']
PMAX_SLS = ['Diamond', 'Platinum', 'Gold', 'Silver', 'Bronze', 'Optimized',
            'None', 'NONE']
PMAX_WLS = ['NONE', 'None']

# Performance
# Metrics
PG_METRICS = [
    'AvgIOSize', 'IOs', 'MBRead', 'MBWritten', 'MBs', 'PercentBusy',
    'Reads', 'Writes']
PORT_METRICS = [
    'AvgIOSize', 'IOs', 'MBRead', 'MBWritten', 'MBs', 'MaxSpeedGBs',
    'PercentBusy', 'ReadResponseTime', 'Reads', 'ResponseTime', 'SpeedGBs',
    'WriteResponseTime', 'Writes']
PORT_RT_METRICS = [
    'AvgIOSize', 'IOs', 'MBRead', 'MBWritten', 'MBs', 'PercentBusy', 'Reads',
    'ResponseTime', 'Writes']

# Cinder config options
LOAD_BALANCE = 'load_balance'
LOAD_BALANCE_RT = 'load_balance_real_time'
PERF_DATA_FORMAT = 'load_data_format'
LOAD_LOOKBACK = 'load_look_back'
LOAD_LOOKBACK_RT = 'load_look_back_real_time'
PORT_GROUP_LOAD_METRIC = 'port_group_load_metric'
PORT_LOAD_METRIC = 'port_load_metric'

# One minute in milliseconds
ONE_MINUTE = 60000
# Default look back windows in minutes
DEFAULT_DIAG_WINDOw = 60
DEFAULT_RT_WINDOW = 1

# REST API keys
PERFORMANCE = 'performance'
REG_DETAILS = 'registrationdetails'
REG_DETAILS_INFO = 'registrationDetailsInfo'
COLLECTION_INT = 'collectionintervalmins'
DIAGNOSTIC = 'diagnostic'
REAL_TIME = 'realtime'
RESULT_LIST = 'resultList'
RESULT = 'result'
KEYS = 'keys'
METRICS = 'metrics'
CAT = 'category'
F_DATE = 'firstAvailableDate'
S_DATE = 'startDate'
L_DATE = 'lastAvailableDate'
E_DATE = 'endDate'
SYMM_ID = 'symmetrixId'
ARRAY_PERF = 'Array'
ARRAY_INFO = 'arrayInfo'
PORT_GROUP = 'PortGroup'
PORT_GROUP_ID = 'portGroupId'
FE_PORT_RT = 'FEPORT'
FE_PORT_DIAG = 'FEPort'
DATA_FORMAT = 'dataFormat'
INST_ID = 'instanceId'
DIR_ID = 'directorId'
PORT_ID = 'portId'

# Revert snapshot exception
REVERT_SS_EXC = 'Link must be fully copied for this operation to proceed'

# extra specs
IS_TRUE = ['<is> True', 'True', 'true', True]
IS_FALSE = ['<is> False', 'False', 'false', False]


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
        short_host_name = self.get_host_short_name_from_fqn(host_name)

        return self.generate_unique_trunc_host(short_host_name)

    @staticmethod
    def get_host_short_name_from_fqn(host_name):
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

        return short_host_name

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
        :returns: snapshot name ready for backend PowerMax/VMAX assignment
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
        if host_name and len(host_name) > UPPER_HOST_CHARS:
            uuid = self.get_uuid_of_input(host_name)
            new_name = ("%(host)s%(uuid)s"
                        % {'host': host_name[-6:],
                           'uuid': uuid})
            host_name = self.truncate_string(new_name, UPPER_HOST_CHARS)
        return host_name

    def get_pg_short_name(self, portgroup_name):
        """Create a unique port group name under 12 characters.

        :param portgroup_name: long portgroup_name
        :returns: truncated portgroup_name
        """
        if portgroup_name and len(portgroup_name) > UPPER_PORT_GROUP_CHARS:
            uuid = self.get_uuid_of_input(portgroup_name)
            new_name = ("%(pg)s%(uuid)s"
                        % {'pg': portgroup_name[-6:],
                           'uuid': uuid})
            portgroup_name = self.truncate_string(
                new_name, UPPER_PORT_GROUP_CHARS)
        return portgroup_name

    @staticmethod
    def get_uuid_of_input(input_str):
        """Get the uuid of the input string

        :param input_str: input string
        :returns: uuid
        """
        input_str = input_str.lower()
        m = md5(usedforsecurity=False)
        m.update(input_str.encode('utf-8'))
        return m.hexdigest()

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
        :returns: snap_name
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

    def is_compression_disabled(self, extra_specs):
        """Check is compression is to be disabled.

        :param extra_specs: extra specifications
        :returns: boolean
        """
        compression_disabled = False

        if extra_specs.get(DISABLECOMPRESSION, False):
            if extra_specs.get(DISABLECOMPRESSION) in IS_TRUE:
                compression_disabled = True
        else:
            if extra_specs.get(SLO):
                service_level = extra_specs.get(SLO)
            else:
                __, __, service_level, __ = self.parse_specs_from_pool_name(
                    extra_specs.get('pool_name'))

            if not service_level:
                compression_disabled = True

        return compression_disabled

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

    def change_replication(self, curr_type_extra_specs, tgt_type_extra_specs):
        """Check if volume types have different replication status.

        :param curr_type_extra_specs: extra specs from source volume type
        :param tgt_type_extra_specs: extra specs from target volume type
        :returns: bool
        """
        change_replication = False
        # Compare non-rep & rep enabled changes
        is_cur_rep = self.is_replication_enabled(curr_type_extra_specs)
        is_tgt_rep = self.is_replication_enabled(tgt_type_extra_specs)
        rep_enabled_diff = is_cur_rep != is_tgt_rep

        if rep_enabled_diff:
            change_replication = True
        elif is_cur_rep:
            # Both types are rep enabled, check for backend id differences
            rdbid = REPLICATION_DEVICE_BACKEND_ID
            curr_rep_backend_id = curr_type_extra_specs.get(rdbid, None)
            tgt_rep_backend_id = tgt_type_extra_specs.get(rdbid, None)
            rdbid_diff = curr_rep_backend_id != tgt_rep_backend_id
            if rdbid_diff:
                change_replication = True

        return change_replication

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
        :returns: rep_configs, replication configuration list
        """
        rep_config = list()
        if not rep_device_list:
            return None
        else:
            for rep_device in rep_device_list:
                rep_config_element = {}
                try:
                    rep_config_element['array'] = rep_device[
                        'target_device_id']
                    rep_config_element['srp'] = rep_device['remote_pool']
                    rep_config_element['rdf_group_label'] = rep_device[
                        'rdf_group_label']
                    rep_config_element['portgroup'] = rep_device[
                        'remote_port_group']

                except KeyError as ke:
                    error_message = (
                        _("Failed to retrieve all necessary SRDF "
                          "information. Error received: %(ke)s.") %
                        {'ke': six.text_type(ke)})
                    LOG.exception(error_message)
                    raise exception.VolumeBackendAPIException(
                        message=error_message)

                try:
                    rep_config_element['sync_retries'] = int(
                        rep_device['sync_retries'])
                    rep_config_element['sync_interval'] = int(
                        rep_device['sync_interval'])
                except (KeyError, ValueError) as ke:
                    LOG.debug(
                        "SRDF Sync wait/retries options not set or set "
                        "incorrectly, defaulting to 200 retries with a 3 "
                        "second wait. Configuration load warning: %(ke)s.",
                        {'ke': six.text_type(ke)})
                    rep_config_element['sync_retries'] = 200
                    rep_config_element['sync_interval'] = 3

                allow_extend = rep_device.get('allow_extend', 'false')
                if strutils.bool_from_string(allow_extend):
                    rep_config_element['allow_extend'] = True
                else:
                    rep_config_element['allow_extend'] = False

                rep_mode = rep_device.get('mode', '')
                if rep_mode.lower() in ['async', 'asynchronous']:
                    rep_config_element['mode'] = REP_ASYNC
                elif rep_mode.lower() == 'metro':
                    rep_config_element['mode'] = REP_METRO
                    metro_bias = rep_device.get('metro_use_bias', 'false')
                    if strutils.bool_from_string(metro_bias):
                        rep_config_element[METROBIAS] = True
                    else:
                        rep_config_element[METROBIAS] = False
                else:
                    rep_config_element['mode'] = REP_SYNC

                backend_id = rep_device.get(BACKEND_ID, '')
                if backend_id:
                    rep_config_element[BACKEND_ID] = backend_id

                rep_config.append(rep_config_element)
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
    def get_grp_volume_model_update(volume, volume_dict, group_id, meta=None):
        """Create and return the volume model update on creation.

        :param volume: volume object
        :param volume_dict: the volume dict
        :param group_id: consistency group id
        :param meta: the volume metadata
        :returns: model_update
        """
        LOG.info("Updating status for group: %(id)s.", {'id': group_id})
        model_update = ({'id': volume.id, 'status': 'available',
                         'provider_location': six.text_type(volume_dict)})
        if meta:
            model_update['metadata'] = meta
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
        intervals_retries_dict = {INTERVAL: interval, RETRIES: retries}
        if isinstance(group, Group):
            for volume_type in group.volume_types:
                extra_specs = self.update_extra_specs(volume_type.extra_specs)
                try:
                    arrays.add(extra_specs[ARRAY])
                except KeyError:
                    return None, intervals_retries_dict
        else:
            msg = (_("Unable to get volume type ids."))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(message=msg)

        if len(arrays) > 1:
            msg = (_("There are multiple arrays "
                     "associated with volume group: %(groupid)s.")
                   % {'groupid': group.id})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(message=msg)
        array = arrays.pop()
        LOG.debug("Serial number %s retrieved from the volume type extra "
                  "specs.", array)
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
        :returns: pools - the updated pool list
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

    @staticmethod
    def add_promotion_pools(pools, primary_array):
        """Add duplicate pools with primary SID for operations during promotion

        :param pools: the pool list
        :param primary_array: the original primary array.
        :returns: pools - the updated pool list
        """
        i_pools = deepcopy(pools)
        for pool in i_pools:
            # pool name
            pool_name = pool['pool_name']
            split_name = pool_name.split('+')
            array_pos = 3 if len(split_name) == 4 else 2
            array_sid = split_name[array_pos]
            updated_pool_name = re.sub(array_sid, primary_array, pool_name)

            # location info
            loc = pool['location_info']
            split_loc = loc.split('#')
            split_loc[0] = primary_array  # Replace the array SID
            updated_loc = '#'.join(split_loc)

            new_pool = deepcopy(pool)
            new_pool['pool_name'] = updated_pool_name
            new_pool['location_info'] = updated_loc
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
        :returns: prefix
        """
        if rep_mode == REP_ASYNC:
            prefix = "-RA"
        elif rep_mode == REP_METRO:
            prefix = "-RM"
        else:
            prefix = "-RE"
        return prefix

    @staticmethod
    def get_rdf_management_group_name(rep_config):
        """Get the name of the group used for async replication management.

        :param rep_config: the replication configuration
        :returns: group name
        """
        grp_name = ("OS-%(rdf)s-%(mode)s-rdf-sg" %
                    {'rdf': rep_config['rdf_group_label'],
                     'mode': rep_config['mode']})
        LOG.debug("The rdf managed group name is %(name)s",
                  {'name': grp_name})
        return grp_name

    def is_metro_device(self, rep_config, extra_specs):
        """Determine if a volume is a Metro enabled device.

        :param rep_config: the replication configuration
        :param extra_specs: the extra specifications
        :returns: bool
        """
        is_metro = (True if self.is_replication_enabled(extra_specs)
                    and rep_config is not None
                    and rep_config.get('mode') == REP_METRO else False)
        return is_metro

    def does_vol_need_rdf_management_group(self, extra_specs):
        """Determine if a volume is a Metro or Async.

        :param extra_specs: the extra specifications
        :returns: bool
        """
        if (self.is_replication_enabled(extra_specs) and
                extra_specs.get(REP_MODE, None) in
                [REP_ASYNC, REP_METRO]):
            return True
        return False

    def derive_default_sg_from_extra_specs(self, extra_specs, rep_mode=None):
        """Get the name of the default sg from the extra specs.

        :param extra_specs: extra specs
        :param rep_mode: replication mode
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
        :returns: temp_grp_name
        """
        temp_grp_name = ("OS-%(rdf)s-temp-rdf-sg"
                         % {'rdf': rep_config['rdf_group_label']})
        LOG.debug("The temp rdf managed group name is %(name)s",
                  {'name': temp_grp_name})
        return temp_grp_name

    def get_child_sg_name(self, host_name, extra_specs, port_group_label):
        """Get the child storage group name for a masking view.

        :param host_name: the short host name
        :param extra_specs: the extra specifications
        :param port_group_label: the port group label
        :returns: child sg name, compression flag, rep flag, short pg name
        """
        do_disable_compression = False
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
                   'pg': port_group_label})
            do_disable_compression = self.is_compression_disabled(
                extra_specs)
            if do_disable_compression:
                child_sg_name = ("%(child_sg_name)s-CD"
                                 % {'child_sg_name': child_sg_name})
        else:
            child_sg_name = (
                "OS-%(shortHostName)s-No_SLO-%(pg)s"
                % {'shortHostName': host_name, 'pg': port_group_label})
        if rep_enabled:
            rep_mode = extra_specs.get(REP_MODE, None)
            child_sg_name += self.get_replication_prefix(rep_mode)
        return child_sg_name, do_disable_compression, rep_enabled

    @staticmethod
    def change_multiattach(extra_specs, new_type_extra_specs):
        """Check if a change in multiattach is required for retype.

        :param extra_specs: the source type extra specs
        :param new_type_extra_specs: the target type extra specs
        :returns: bool
        """
        is_src_multiattach = volume_utils.is_boolean_str(
            extra_specs.get('multiattach'))
        is_tgt_multiattach = volume_utils.is_boolean_str(
            new_type_extra_specs.get('multiattach'))
        return is_src_multiattach != is_tgt_multiattach

    @staticmethod
    def is_volume_manageable(source_vol):
        """Check if a volume with verbose description is valid for management.

        :param source_vol: the verbose volume dict
        :returns: bool True/False
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

        if vol_head['userDefinedIdentifier'][0:3] == 'OS-':
            return False

        return True

    @staticmethod
    def is_snapshot_manageable(source_vol):
        """Check if a volume with snapshot description is valid for management.

        :param source_vol: the verbose volume dict
        :returns: bool True/False
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

    def get_volume_attached_hostname(self, volume):
        """Get the host name from the attached volume

        :param volume: the volume object
        :returns: str -- the attached hostname
        """
        host_name_set = set()
        attachment_list = volume.volume_attachment
        LOG.debug("Volume attachment list: %(atl)s. "
                  "Attachment type: %(at)s",
                  {'atl': attachment_list, 'at': type(attachment_list)})

        try:
            att_list = attachment_list.objects
        except AttributeError:
            att_list = attachment_list
        for att in att_list:
            host_name_set.add(att.attached_host)

        if host_name_set:
            if len(host_name_set) > 1:
                LOG.warning("Volume is attached to multiple instances "
                            "on more than one compute node.")
            else:
                return host_name_set.pop()
        return None

    def get_rdf_managed_storage_group(self, device_info):
        """Get the RDF managed storage group

        :param device_info: the device info dict
        :returns: str -- the attached hostname
                 dict -- storage group details
        """
        try:
            sg_list = device_info.get("storageGroupId")
            for sg_id in sg_list:
                sg_details = self.get_rdf_group_component_dict(sg_id)
                if sg_details:
                    return sg_id, sg_details
        except IndexError:
            return None, None
        return None, None

    def get_production_storage_group(self, device_info):
        """Get the production storage group

        :param device_info: the device info dict
        :returns: str -- the storage group id
                 dict -- storage group details
        """
        try:
            sg_list = device_info.get("storageGroupId")
            for sg_id in sg_list:
                sg_details = self.get_storage_group_component_dict(sg_id)
                if sg_details:
                    return sg_id, sg_details
        except IndexError:
            return None, None
        return None, None

    @staticmethod
    def validate_qos_input(input_key, sg_value, qos_extra_spec, property_dict):
        max_value = 100000
        qos_unit = "IO/Sec"
        if input_key == 'total_iops_sec':
            min_value = 100
            input_value = int(qos_extra_spec['total_iops_sec'])
            sg_key = 'host_io_limit_io_sec'
        else:
            qos_unit = "MB/sec"
            min_value = 1
            input_value = int(
                int(qos_extra_spec['total_bytes_sec']) / units.Mi)
            sg_key = 'host_io_limit_mb_sec'
        if min_value <= input_value <= max_value:
            if sg_value is None or input_value != int(sg_value):
                property_dict[sg_key] = input_value
        else:
            exception_message = (
                _("Invalid %(ds)s with value %(dt)s entered. Valid values "
                  "range from %(du)s %(dv)s to 100,000 %(dv)s") % {
                    'ds': input_key, 'dt': input_value, 'du': min_value,
                    'dv': qos_unit})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        return property_dict

    @staticmethod
    def validate_qos_distribution_type(
            sg_value, qos_extra_spec, property_dict):
        dynamic_list = ['never', 'onfailure', 'always']
        if qos_extra_spec.get('DistributionType').lower() in dynamic_list:
            distribution_type = qos_extra_spec['DistributionType']
            if distribution_type != sg_value:
                property_dict["dynamicDistribution"] = distribution_type
        else:
            exception_message = (
                _("Wrong Distribution type value %(dt)s entered. Please "
                  "enter one of: %(dl)s") % {
                    'dt': qos_extra_spec.get('DistributionType'),
                    'dl': dynamic_list})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        return property_dict

    @staticmethod
    def validate_multiple_rep_device(rep_devices):
        """Validate the validity of multiple replication devices.

        Validates uniqueness and presence of backend ids in rep_devices,
        consistency in target arrays and replication modes when multiple
        replication devices are present in cinder.conf.

        :param rep_devices: rep_devices imported from cinder.conf --list
        """
        rdf_group_labels = set()
        backend_ids = set()
        rep_modes = set()
        target_arrays = set()

        repdev_count = len(rep_devices)
        if repdev_count > 3:
            msg = (_('Up to three replication_devices are currently '
                     'supported, one for each replication mode. '
                     '%d replication_devices found in cinder.conf.')
                   % repdev_count)
            raise exception.InvalidConfigurationValue(msg)

        for rep_device in rep_devices:
            backend_id = rep_device.get(BACKEND_ID)
            if backend_id:
                if backend_id in backend_ids:
                    msg = (_('Backend IDs must be unique across all '
                             'rep_device when multiple replication devices '
                             'are defined in cinder.conf, backend_id %s is '
                             'defined more than once.') % backend_id)
                    raise exception.InvalidConfigurationValue(msg)
                elif backend_id == PMAX_FAILOVER_START_ARRAY_PROMOTION:
                    msg = (_('Invalid Backend ID found. Defining a '
                             'replication device with a Backend ID of %s is '
                             'currently not supported. Please update '
                             'the Backend ID of the related replication '
                             'device in cinder.conf to use valid '
                             'Backend ID value.') % backend_id)
                    raise exception.InvalidConfigurationValue(msg)
            else:
                msg = _('Backend IDs must be assigned for each rep_device '
                        'when multiple replication devices are defined in '
                        'cinder.conf.')
                raise exception.InvalidConfigurationValue(msg)
            backend_ids.add(backend_id)

            rdf_group_label = rep_device.get('rdf_group_label')
            if rdf_group_label in rdf_group_labels:
                msg = (_('RDF Group Labels must be unique across all '
                         'rep_device when multiple replication devices are '
                         'defined in cinder.conf. RDF Group Label %s is '
                         'defined more than once.') % rdf_group_label)
                raise exception.InvalidConfigurationValue(msg)
            rdf_group_labels.add(rdf_group_label)

            rep_mode = rep_device.get('mode', '')
            if rep_mode.lower() in ['async', 'asynchronous']:
                rep_mode = REP_ASYNC
            elif rep_mode.lower() == 'metro':
                rep_mode = REP_METRO
            else:
                rep_mode = REP_SYNC
            if rep_mode in rep_modes:
                msg = (_('RDF Modes must be unique across all '
                         'replication_device. Found multiple instances of %s '
                         'mode defined in cinder.conf.') % rep_mode)
                raise exception.InvalidConfigurationValue(msg)
            rep_modes.add(rep_mode)

            target_device_id = rep_device.get('target_device_id')
            target_arrays.add(target_device_id)

        target_arrays.discard(None)
        if len(target_arrays) > 1:
            msg = _('Found multiple target_device_id set in cinder.conf. A '
                    'single target_device_id value must be used across all '
                    'replication device when defining using multiple '
                    'replication devices.')
            raise exception.InvalidConfigurationValue(msg)

    @staticmethod
    def compare_cylinders(cylinders_source, cylinder_target):
        """Compare number of cylinders of source and target.

        :param cylinders_source: number of cylinders on source
        :param cylinder_target: number of cylinders on target
        """
        if float(cylinders_source) > float(cylinder_target):
            exception_message = (
                _("The number of source cylinders %(cylinders_source)s "
                  "cannot be greater than the number of target cylinders "
                  "%(cylinder_target)s. Please extend your source volume by "
                  "at least 1GiB.") % {
                    'cylinders_source': cylinders_source,
                    'cylinder_target': cylinder_target})
            raise exception.VolumeBackendAPIException(
                message=exception_message)

    @staticmethod
    def get_service_level_workload(extra_specs):
        """Get the service level and workload combination from extra specs.

        :param extra_specs: extra specifications
        :returns: string, string
        """
        service_level, workload = 'None', 'None'
        if extra_specs.get(SLO):
            service_level = extra_specs.get(SLO)
            if (extra_specs.get(WORKLOAD)
                    and 'NONE' not in extra_specs.get(WORKLOAD)):
                workload = extra_specs.get(WORKLOAD)
        return service_level, workload

    def get_new_tags(self, list_str1, list_str2):
        """Get elements in list_str1 not in list_str2

        :param list_str1: list one in string format
        :param list_str2: list two in string format
        :returns: list
        """
        list_str1 = re.sub(r"\s+", "", list_str1)
        if not list_str1:
            return []
        common_list = self._get_intersection(
            list_str1, list_str2)

        my_list1 = sorted(list_str1.split(","))
        return [x for x in my_list1 if x.lower() not in common_list]

    def verify_tag_list(self, tag_list):
        """Verify that the tag list has allowable character

        :param tag_list: list of tags
        :returns: boolean
        """
        if not tag_list:
            return False
        if not isinstance(tag_list, list):
            LOG.warning("The list of tags %(tag_list)s is not "
                        "in list format. Tagging will not proceed.",
                        {'tag_list': tag_list})
            return False
        if len(tag_list) > 8:
            LOG.warning("The list of tags %(tag_list)s is more "
                        "than the upper limit of 8. Tagging will not "
                        "proceed.",
                        {'tag_list': tag_list})
            return False
        for tag in tag_list:
            tag = tag.strip()
            if not re.match('^[a-zA-Z0-9_\\-]+$', tag):
                return False
        return True

    def convert_list_to_string(self, list_input):
        """Convert a list to a comma separated list

        :param list_input: list
        :returns: string or None
        """
        return ','.join(map(str, list_input)) if isinstance(
            list_input, list) else list_input

    def validate_short_host_name_from_template(
            self, short_host_template, short_host_name):
        """Validate that the short host name is in a format we can use.

        Can be one of
        shortHostName - where shortHostName is what the driver specifies
        it to be, default
        shortHostName[:x]uuid[:x] - where first x characters of the short
        host name and x uuid characters created from md5 hash of
        short host name
        shortHostName[:x]userdef - where first x characters of the short
        host name and a user defined name
        shortHostName[-x:]uuid[:x] - where last x characters of short host
        name and x uuid characters created from md5 hash of short host
        name
        shortHostName[-x:]suserdef - where last x characters of the short
        host name and a user defined name

        :param short_host_template: short host name template
        :param short_host_name: short host name
        :raises: VolumeBackendAPIException
        :returns: new short host name -- string
        """
        new_short_host_name = None
        is_ok, case = self.regex_check(short_host_template, True)
        if is_ok:
            new_short_host_name = (
                self.generate_entity_string(
                    case, short_host_template, short_host_name, True))
        if not new_short_host_name:
            error_message = (_('Unable to generate string from short '
                               'host template %(template)s. Please refer to '
                               'the online documentation for correct '
                               'template format(s) for short host name.') %
                             {'template': short_host_template})
            LOG.error(error_message)
            raise exception.VolumeBackendAPIException(
                message=error_message)

        return new_short_host_name

    def validate_port_group_name_from_template(
            self, port_group_template, port_group_name):
        """Validate that the port group name is in a format we can use.

        Can be one of
        portGroupName - where portGroupName is what the driver specifies
        it to be, default
        portGroupName[:x]uuid[:x] - where first x characters of the short
        host name and x uuid characters created from md5 hash of
        short host name
        portGroupName[:x]userdef - where first x characters of the short
        host name and a user defined name
        portGroupName[-x:]uuid[:x] - where last x characters of short host
        name and x uuid characters created from md5 hash of short host
        name
        portGroupName[-x:]userdef - where last x characters of the short
        host name and a user defined name

        :param port_group_template: port group name template
        :param port_group_name: port group name
        :raises: VolumeBackendAPIException
        :returns: new port group name -- string
        """
        new_port_group_name = None
        is_ok, case = self.regex_check(port_group_template, False)
        if is_ok:
            new_port_group_name = (
                self.generate_entity_string(
                    case, port_group_template, port_group_name, False))

        if not new_port_group_name:
            error_message = (_('Unable to generate string from port group '
                               'template %(template)s.  Please refer to '
                               'the online documentation for correct '
                               'template format(s) for port groups.') %
                             {'template': port_group_template})
            LOG.error(error_message)
            raise exception.VolumeBackendAPIException(
                message=error_message)

        return new_port_group_name

    def generate_entity_string(
            self, case, entity_template, entity_name, entity_flag):
        """Generate the entity string if the template checks out

        :param case: one of five cases
        :param entity_template: entity template
        :param entity_name: entity name
        :param entity_flag: storage group or port group flag
        :returns: new entity name -- string
        """
        new_entity_name = None
        override_rule_warning = False
        try:
            if case == '1':
                new_entity_name = self.get_name_if_default_template(
                    entity_name, entity_flag)
            elif case == '2':
                pass_two, uuid = self.prepare_string_with_uuid(
                    entity_template, entity_name, entity_flag)
                m = re.match(r'^' + entity_name +
                             r'\[:(\d+)\]' + uuid + r'\[:(\d+)\]$', pass_two)
                if m:
                    num_1 = m.group(1)
                    num_2 = m.group(2)
                    self.check_upper_limit(
                        int(num_1), int(num_2), entity_flag)
                    new_entity_name = (
                        entity_name[:int(num_1)] + uuid[:int(num_2)])
                override_rule_warning = True
            elif case == '3':
                pass_two, uuid = self.prepare_string_with_uuid(
                    entity_template, entity_name, entity_flag)
                m = re.match(r'^' + entity_name +
                             r'\[-(\d+):\]' + uuid + r'\[:(\d+)\]$', pass_two)
                if m:
                    num_1 = m.group(1)
                    num_2 = m.group(2)
                    self.check_upper_limit(
                        int(num_1), int(num_2), entity_flag)
                    new_entity_name = (
                        entity_name[-int(num_1):] + uuid[:int(num_2)])
                override_rule_warning = True
            elif case == '4':
                pass_two = self.prepare_string_entity(
                    entity_template, entity_name, entity_flag)
                m = re.match(r'^' + entity_name +
                             r'\[:(\d+)\]' + r'([a-zA-Z0-9_\\-]+)$', pass_two)
                if m:
                    num_1 = m.group(1)
                    user_defined = m.group(2)
                    self.check_upper_limit(
                        int(num_1), len(user_defined), entity_flag)
                    new_entity_name = entity_name[:int(num_1)] + user_defined
                override_rule_warning = True
            elif case == '5':
                pass_two = self.prepare_string_entity(
                    entity_template, entity_name, entity_flag)
                m = re.match(r'^' + entity_name +
                             r'\[-(\d+):\]' + r'([a-zA-Z0-9_\\-]+)$', pass_two)
                if m:
                    num_1 = m.group(1)
                    user_defined = m.group(2)
                    self.check_upper_limit(
                        int(num_1), len(user_defined), entity_flag)
                    new_entity_name = entity_name[-int(num_1):] + user_defined
                override_rule_warning = True
            if override_rule_warning:
                LOG.warning(
                    "You have opted to override the %(entity)s naming format. "
                    "Once changed and you have attached volumes or created "
                    "new instances, you cannot revert to default or change to "
                    "another format.",
                    {'entity': 'storage group'
                        if entity_flag else 'port group'})

        except Exception:
            new_entity_name = None
        return new_entity_name

    def get_name_if_default_template(self, entity_name, is_short_host_flag):
        """Get the entity name if it is the default template

        :param entity_name: the first number
        :param is_short_host_flag: the second number
        :returns: entity name -- string
        """
        if is_short_host_flag:
            return self.get_host_short_name(entity_name)
        else:
            return self.get_pg_short_name(entity_name)

    @staticmethod
    def check_upper_limit(num_1, num_2, is_host_flag):
        """Check that the sum of number is less than upper limit.

        :param num_1: the first number
        :param num_2: the second number
        :param is_host_flag: is short host boolean
        :raises: VolumeBackendAPIException
        """
        if is_host_flag:
            if (num_1 + num_2) > UPPER_HOST_CHARS:
                error_message = (_("Host name exceeds the character upper "
                                   "limit of %(upper)d.  Please check your "
                                   "short host template.") %
                                 {'upper': UPPER_HOST_CHARS})
                LOG.error(error_message)
                raise exception.VolumeBackendAPIException(
                    message=error_message)
        else:
            if (num_1 + num_2) > UPPER_PORT_GROUP_CHARS:
                error_message = (_("Port group name exceeds the character "
                                   "upper limit of %(upper)d. Please check "
                                   "your port group template") %
                                 {'upper': UPPER_PORT_GROUP_CHARS})
                LOG.error(error_message)
                raise exception.VolumeBackendAPIException(
                    message=error_message)

    def prepare_string_with_uuid(
            self, template, entity_str, is_short_host_flag):
        """Prepare string for pass three

        :param template: the template
        :param entity_str: the entity string
        :param is_short_host_flag: is short host
        :returns: pass_two -- string
                  uuid -- string
        """
        pass_one = self.prepare_string_entity(
            template, entity_str, is_short_host_flag)
        uuid = self.get_uuid_of_input(entity_str)
        pass_two = pass_one.replace('uuid', uuid)
        return pass_two, uuid

    @staticmethod
    def prepare_string_entity(template, entity_str, is_host_flag):
        """Prepare string for pass two

        :param template: the template
        :param entity_str: the entity string
        :param is_host_flag: is host boolean
        :returns: pass_one -- string
        """
        entity_type = 'shortHostName' if is_host_flag else 'portGroupName'
        # Replace entity type with variable
        return template.replace(
            entity_type, entity_str)

    @staticmethod
    def regex_check(template, is_short_host_flag):
        """Check the template is in a validate format.

        :param template: short host name template
        :param is_short_host_flag: short host boolean
        :returns: boolean,
                  case -- string
        """
        if is_short_host_flag:
            entity = 'shortHostName'
        else:
            entity = 'portGroupName'
        if re.match(r'^' + entity + r'$', template):
            return True, '1'
        elif re.match(r'^' + entity + r'\[:\d+\]uuid\[:\d+\]$', template):
            return True, '2'
        elif re.match(r'^' + entity + r'\[-\d+:\]uuid\[:\d+\]$', template):
            return True, '3'
        elif re.match(r'^' + entity + r'\[:\d+\][a-zA-Z0-9_\\-]+$', template):
            return True, '4'
        elif re.match(r'^' + entity + r'\[-\d+:\][a-zA-Z0-9_\\-]+$',
                      template):
            return True, '5'
        return False, '0'

    def get_host_name_label(self, host_name_in, host_template):
        """Get the host name label that will be used in PowerMax Objects

        :param host_name_in: host name as portrayed in connector object
        :param host_template:
        :returns: host_name_out
        """
        host_name_out = self.get_host_short_name(
            host_name_in)
        if host_template:
            short_host_name = self.get_host_short_name_from_fqn(
                host_name_in)
            host_name_out = (
                self.validate_short_host_name_from_template(
                    host_template, short_host_name))
        return host_name_out

    def get_port_name_label(self, port_name_in, port_group_template):
        """Get the port name label that will be used in PowerMax Objects

        :rtype: object
        :param host_name_in: host name as portrayed in connector object
        :param port_group_template: port group template
        :returns: port_name_out
        """
        port_name_out = self.get_pg_short_name(port_name_in)
        if port_group_template:
            port_name_out = (
                self.validate_port_group_name_from_template(
                    port_group_template, port_name_in))
        return port_name_out

    def get_storage_group_component_dict(self, storage_group_name):
        """Parse the storage group string.

        :param storage_group_name: the storage group name -- str
        :returns: object components -- dict
        """
        regex_str = (r'^(?P<prefix>OS)-(?P<host>.+?)'
                     r'((?P<no_slo>No_SLO)|((?P<srp>SRP.+?)-'
                     r'(?P<sloworkload>.+?)))-(?P<portgroup>.+?)'
                     r'(?P<after_pg>$|-CD|-RE|-RA|-RM)')
        return self.get_object_components_and_correct_host(
            regex_str, storage_group_name)

    def get_rdf_group_component_dict(self, storage_group_name):
        """Parse the storage group string.

        :param storage_group_name: the storage group name -- str
        :returns: object components -- dict
        """
        regex_str = (r'^(?P<prefix>OS)-(?P<rdf_label>.+?)-'
                     r'(?P<sync_mode>Asynchronous|Metro)-'
                     r'(?P<after_mode>rdf-sg)$')
        return self.get_object_components(
            regex_str, storage_group_name)

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

    def get_possible_initiator_name(self, host_label, protocol):
        """Get possible initiator name based on the host

        :param host_label: the host label -- str
        :param protocol: the protocol -- str
        :returns: initiator_group_name -- str
        """
        protocol = self.get_short_protocol_type(protocol)
        return ("OS-%(shortHostName)s-%(protocol)s-IG"
                % {'shortHostName': host_label,
                   'protocol': protocol})

    @staticmethod
    def delete_values_from_dict(datadict, key_list):
        """Delete values from a dict

        :param datadict: dictionary
        :param key_list: list of keys
        :returns: dict
        """
        for key in key_list:
            if datadict.get(key):
                del datadict[key]
        return datadict

    @staticmethod
    def update_values_in_dict(datadict, tuple_list):
        """Delete values from a dict

        :param datadict: dictionary
        :param tuple_list: list of tuples
        :returns: dict
        """
        for tuple in tuple_list:
            if datadict.get(tuple[0]):
                datadict.update({tuple[1]: datadict.get(tuple[0])})
                del datadict[tuple[0]]
        return datadict

    @staticmethod
    def _get_intersection(list_str1, list_str2):
        """Get the common values between 2 comma separated list

        :param list_str1: list one
        :param list_str2: list two
        :returns: sorted list
        """
        list_str1 = re.sub(r"\s+", "", list_str1).lower()
        list_str2 = re.sub(r"\s+", "", list_str2).lower()
        my_list1 = sorted(list_str1.split(","))
        my_list2 = sorted(list_str2.split(","))
        sorted_common_list = (
            sorted(list(set(my_list1).intersection(set(my_list2)))))
        return sorted_common_list

    @staticmethod
    def get_unique_device_ids_from_lists(list_a, list_b):
        """Get the unique values from list B that don't appear in list A.

        :param list_a: list A
        :param list_b: list B
        :returns: values unique between two lists -- list
        """
        set_a = set(list_a)
        return [dev_id for dev_id in list_b if dev_id not in set_a]

    @staticmethod
    def update_payload_for_rdf_vol_create(payload, remote_array_id,
                                          storage_group_name):
        """Construct the REST payload for creating RDF enabled volumes.

        :param payload: the existing payload -- dict
        :param remote_array_id: the remote array serial number -- str
        :param storage_group_name: the storage group name -- str
        :returns: updated payload -- dict
        """
        create_new_vol = {"create_new_volumes": "True"}
        payload["editStorageGroupActionParam"]["expandStorageGroupParam"][
            "addVolumeParam"].update(create_new_vol)
        remote_dict = {"remoteSymmSGInfoParam": {
            "remote_symmetrix_1_id": remote_array_id,
            "remote_symmetrix_1_sgs": [storage_group_name],
            "force": "true"}}

        payload["editStorageGroupActionParam"]["expandStorageGroupParam"][
            "addVolumeParam"].update(remote_dict)

        return payload

    @staticmethod
    def is_retype_supported(volume, src_extra_specs, tgt_extra_specs,
                            rep_configs):
        """Determine if a retype operation involving Metro is supported.

        :param volume: the volume object -- obj
        :param src_extra_specs: the source extra specs -- dict
        :param tgt_extra_specs: the target extra specs -- dict
        :param rep_configs: imported cinder.conf replication devices -- dict
        :returns: is supported -- bool
        """
        if volume.attach_status == 'detached':
            return True

        src_rep_mode = src_extra_specs.get('rep_mode', None)
        tgt_rep_mode = None
        if PowerMaxUtils.is_replication_enabled(tgt_extra_specs):
            target_backend_id = tgt_extra_specs.get(
                REPLICATION_DEVICE_BACKEND_ID, BACKEND_ID_LEGACY_REP)
            target_rep_config = PowerMaxUtils.get_rep_config(
                target_backend_id, rep_configs)
            tgt_rep_mode = target_rep_config.get('mode', REP_SYNC)

        if tgt_rep_mode != REP_METRO:
            return True
        else:
            if src_rep_mode == REP_METRO:
                return True
            else:
                if not src_rep_mode or src_rep_mode in [REP_SYNC, REP_ASYNC]:
                    return False

    @staticmethod
    def get_rep_config(backend_id, rep_configs, promotion_vol_stats=False):
        """Get rep_config for given backend_id.

        :param backend_id: rep config search key -- str
        :param rep_configs: backend rep_configs -- list
        :param promotion_vol_stats: get rep config for vol stats -- bool
        :returns: rep_config -- dict
        """
        if len(rep_configs) == 1:
            rep_device = rep_configs[0]
        else:
            rep_device = None
            for rep_config in rep_configs:
                if rep_config[BACKEND_ID] == backend_id:
                    rep_device = rep_config
            if rep_device is None:
                if promotion_vol_stats:
                    # Stat collection only need remote array and srp, any of
                    # the available replication_devices can provide this.
                    rep_device = rep_configs[0]
                else:
                    msg = (_('Could not find a replication_device with a '
                             'backend_id of "%s" in cinder.conf. Please '
                             'confirm that the replication_device_backend_id '
                             'extra spec for this volume type matches the '
                             'backend_id of the intended replication_device '
                             'in cinder.conf.') % backend_id)
                    if BACKEND_ID_LEGACY_REP in msg:
                        msg = (_('Could not find replication_device. Legacy '
                                 'replication_device key found, please ensure '
                                 'the backend_id for the legacy '
                                 'replication_device in cinder.conf has been '
                                 'changed to "%s".') % BACKEND_ID_LEGACY_REP)
                    LOG.error(msg)
                    raise exception.InvalidInput(msg)
        return rep_device

    @staticmethod
    def get_replication_targets(rep_configs):
        """Set the replication targets for the backend.

        :param rep_configs: backend rep_configs -- list
        :returns: arrays configured for replication -- list
        """
        replication_targets = set()
        if rep_configs:
            for rep_config in rep_configs:
                array = rep_config.get(ARRAY)
                if array:
                    replication_targets.add(array)
        return list(replication_targets)

    def validate_failover_request(self, is_failed_over, failover_backend_id,
                                  rep_configs, primary_array, arrays_list,
                                  is_promoted):
        """Validate failover_host request's parameters

        Validate that a failover_host operation can be performed with
        the user entered parameters and system configuration/state

        :param is_failed_over: current failover state
        :param failover_backend_id: backend_id given during failover request
        :param rep_configs: backend rep_configs -- list
        :param primary_array: configured primary array SID -- string
        :param arrays_list: list of U4P symmetrix IDs -- list
        :param is_promoted: current promotion state -- bool
        :return: (bool, str) is valid, reason on invalid
        """
        is_valid = True
        msg = ""
        if is_failed_over:
            valid_backend_ids = [
                'default', PMAX_FAILOVER_START_ARRAY_PROMOTION]
            if failover_backend_id not in valid_backend_ids:
                is_valid = False
                msg = _('Cannot failover, the backend is already in a failed '
                        'over state, if you meant to failback, please add '
                        '--backend_id default to the command.')
            elif (failover_backend_id == 'default' and
                  primary_array not in arrays_list):
                is_valid = False
                msg = _('Cannot failback, the configured primary array is '
                        'not currently available to perform failback to. '
                        'Please ensure array %s is visible in '
                        'Unisphere.') % primary_array
            elif is_promoted and failover_backend_id != 'default':
                is_valid = False
                msg = _('Failover promotion currently in progress, please '
                        'finish the promotion process and issue a failover '
                        'using the "default" backend_id to complete this '
                        'process.')
        else:
            if failover_backend_id == 'default':
                is_valid = False
                msg = _('Cannot failback, backend is not in a failed over '
                        'state. If you meant to failover, please either omit '
                        'the --backend_id parameter or use the --backend_id '
                        'parameter with a valid backend id.')
        return is_valid, msg

    def validate_replication_group_config(self, rep_configs, extra_specs_list):
        """Validate replication group configuration

        Validate the extra specs of volume types being added to
        a volume group against rep_config imported from cinder.conf

        :param rep_configs: list of replication_device dicts from cinder.conf
        :param extra_specs_list: extra_specs of volume types added to group
        :raises InvalidInput: If any of the validation check fail
        """
        if not rep_configs:
            LOG.error('No replication devices set in cinder.conf please '
                      'disable replication in Volume Group extra specs '
                      'or add replication device to cinder.conf.')
            msg = _('No replication devices are defined in cinder.conf, '
                    'can not enable volume group replication.')
            raise exception.InvalidInput(reason=msg)

        rep_group_backend_ids = set()
        for extra_specs in extra_specs_list:
            target_backend_id = extra_specs.get(
                REPLICATION_DEVICE_BACKEND_ID,
                BACKEND_ID_LEGACY_REP)
            try:
                target_rep_config = self.get_rep_config(
                    target_backend_id, rep_configs)
                rep_group_backend_ids.add(target_backend_id)
            except exception.InvalidInput:
                target_rep_config = None

            if not (extra_specs.get(IS_RE) == '<is> True'):
                # Replication is disabled or not set to correct value
                # in the Volume Type being added
                msg = _('Replication is not enabled for a Volume Type, '
                        'all Volume Types in a replication enabled '
                        'Volume Group must have replication enabled.')
                raise exception.InvalidInput(reason=msg)

            if not target_rep_config:
                # Unable to determine rep_configs to use.
                msg = _('Unable to determine which rep_device to use from '
                        'cinder.conf. Could not validate volume types being '
                        'added to group.')
                raise exception.InvalidInput(reason=msg)

            # Verify that replication is Synchronous mode
            if not target_rep_config.get('mode'):
                LOG.warning('Unable to verify the replication mode '
                            'of Volume Type, please ensure only '
                            'Synchronous replication is used.')
            elif not target_rep_config['mode'] == REP_SYNC:
                msg = _('Replication for Volume Type is not set '
                        'to Synchronous. Only Synchronous '
                        'can be used with replication groups')
                raise exception.InvalidInput(reason=msg)

        if len(rep_group_backend_ids) > 1:
            # We should only have a single backend_id
            # (replication type) across all the Volume Types
            msg = _('Multiple replication backend ids detected '
                    'please ensure only a single replication device '
                    '(backend_id) is used for all Volume Types in a '
                    'Volume Group.')
            raise exception.InvalidInput(reason=msg)

    @staticmethod
    def validate_non_replication_group_config(extra_specs_list):
        """Validate volume group configuration

        Validate that none of the Volume Type extra specs are
        replication enabled.

        :param extra_specs_list: list of Volume Type extra specs
        :return: bool replication enabled found in any extra specs
        """
        for extra_specs in extra_specs_list:
            if extra_specs.get(IS_RE) == '<is> True':
                msg = _('Replication is enabled in one or more of the '
                        'Volume Types being added to new Volume Group but '
                        'the Volume Group is not replication enabled. Please '
                        'enable replication in the Volume Group or select '
                        'only non-replicated Volume Types.')
                raise exception.InvalidInput(reason=msg)

    @staticmethod
    def get_migration_delete_extra_specs(volume, extra_specs, rep_configs):
        """Get previous extra specs rep details during migration delete

        :param volume: volume object -- volume
        :param extra_specs: volumes extra specs -- dict
        :param rep_configs: imported cinder.conf replication devices -- dict
        :returns: updated extra specs -- dict
        """
        metadata = volume.metadata
        replication_enabled = strutils.bool_from_string(
            metadata.get(IS_RE_CAMEL, 'False'))
        if replication_enabled:
            rdfg_label = metadata['RDFG-Label']
            rep_config = next(
                (r_c for r_c in rep_configs if r_c[
                    'rdf_group_label'] == rdfg_label), None)

            extra_specs[IS_RE] = replication_enabled
            extra_specs[REP_MODE] = metadata['ReplicationMode']
            extra_specs[REP_CONFIG] = rep_config
            extra_specs[REPLICATION_DEVICE_BACKEND_ID] = rep_config[BACKEND_ID]
        else:
            extra_specs.pop(IS_RE, None)
        return extra_specs

    @staticmethod
    def version_meet_req(version, minimum_version):
        """Check if current version meets the minimum version allowed

        :param version: unisphere version
        :param minimum_version: minimum version allowed
        :returns: boolean
        """
        checking = packaging.version.parse(version)
        minimum = packaging.version.parse(minimum_version)
        return checking >= minimum

    @staticmethod
    def parse_specs_from_pool_name(pool_name):
        """Parse basic volume type specs from pool_name.

        :param pool_name: the pool name -- str
        :returns: array_id, srp, service_level, workload -- str, str, str, str
        """
        array_id, srp, service_level, workload = str(), str(), str(), str()

        pool_details = pool_name.split('+')
        if len(pool_details) == 4:
            array_id = pool_details[3]
            srp = pool_details[2]
            service_level = pool_details[0]
            if not pool_details[1].lower() == 'none':
                workload = pool_details[1]
        elif len(pool_details) == 3:
            service_level = pool_details[0]
            srp = pool_details[1]
            array_id = pool_details[2]
        else:
            if not pool_name:
                msg = (_('No pool_name specified in volume-type.'))
            else:
                msg = (_("There has been a problem parsing the pool "
                         "information from pool_name '%(pool)s'." % {
                             'pool': pool_name}))

            raise exception.VolumeBackendAPIException(msg)

        if service_level.lower() == 'none':
            service_level = str()

        return array_id, srp, service_level, workload
