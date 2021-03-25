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

import ast
from copy import deepcopy
import math
import random
import sys
import time

from oslo_config import cfg
from oslo_config import types
from oslo_log import log as logging
import six

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder.utils import retry
from cinder.volume import configuration
from cinder.volume.drivers.dell_emc.powermax import masking
from cinder.volume.drivers.dell_emc.powermax import metadata as volume_metadata
from cinder.volume.drivers.dell_emc.powermax import migrate
from cinder.volume.drivers.dell_emc.powermax import performance
from cinder.volume.drivers.dell_emc.powermax import provision
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume.drivers.dell_emc.powermax import utils
from cinder.volume import volume_types
from cinder.volume import volume_utils
LOG = logging.getLogger(__name__)

CONF = cfg.CONF

BACKENDNAME = 'volume_backend_name'
PREFIXBACKENDNAME = 'capabilities:volume_backend_name'

# Replication
REPLICATION_DISABLED = fields.ReplicationStatus.DISABLED
REPLICATION_ENABLED = fields.ReplicationStatus.ENABLED
REPLICATION_FAILOVER = fields.ReplicationStatus.FAILED_OVER
FAILOVER_ERROR = fields.ReplicationStatus.FAILOVER_ERROR
REPLICATION_ERROR = fields.ReplicationStatus.ERROR

retry_exc_tuple = (exception.VolumeBackendAPIException,)


powermax_opts = [
    cfg.IntOpt('interval',
               default=3,
               help='Use this value to specify '
                    'length of the interval in seconds.'),
    cfg.IntOpt('retries',
               default=200,
               help='Use this value to specify '
                    'number of retries.'),
    cfg.BoolOpt('initiator_check',
                default=False,
                help='Use this value to enable '
                     'the initiator_check.'),
    cfg.StrOpt(utils.VMAX_WORKLOAD,
               help='Workload, setting this as an extra spec in '
                    'pool_name is preferable.'),
    cfg.IntOpt(utils.U4P_FAILOVER_TIMEOUT,
               default=20.0,
               help='How long to wait for the server to send data before '
                    'giving up.'),
    cfg.IntOpt(utils.U4P_FAILOVER_RETRIES,
               default=3,
               help='The maximum number of retries each connection should '
                    'attempt. Note, this applies only to failed DNS lookups, '
                    'socket connections and connection timeouts, never to '
                    'requests where data has made it to the server.'),
    cfg.IntOpt(utils.U4P_FAILOVER_BACKOFF_FACTOR,
               default=1,
               help='A backoff factor to apply between attempts after the '
                    'second try (most errors are resolved immediately by a '
                    'second try without a delay). Retries will sleep for: '
                    '{backoff factor} * (2 ^ ({number of total retries} - 1)) '
                    'seconds.'),
    cfg.BoolOpt(utils.U4P_FAILOVER_AUTOFAILBACK,
                default=True,
                help='If the driver should automatically failback to the '
                     'primary instance of Unisphere when a successful '
                     'connection is re-established.'),
    cfg.MultiOpt(utils.U4P_FAILOVER_TARGETS,
                 item_type=types.Dict(),
                 help='Dictionary of Unisphere failover target info.'),
    cfg.StrOpt(utils.POWERMAX_ARRAY,
               help='Serial number of the array to connect to.'),
    cfg.StrOpt(utils.POWERMAX_SRP,
               help='Storage resource pool on array to use for '
                    'provisioning.'),
    cfg.StrOpt(utils.POWERMAX_SERVICE_LEVEL,
               help='Service level to use for provisioning storage. '
                    'Setting this as an extra spec in pool_name '
                    'is preferable.'),
    cfg.ListOpt(utils.POWERMAX_PORT_GROUPS,
                bounds=True,
                help='List of port groups containing frontend ports '
                     'configured prior for server connection.'),
    cfg.ListOpt(utils.POWERMAX_ARRAY_TAG_LIST,
                bounds=True,
                help='List of user assigned name for storage array.'),
    cfg.StrOpt(utils.POWERMAX_SHORT_HOST_NAME_TEMPLATE,
               default='shortHostName',
               help='User defined override for short host name.'),
    cfg.StrOpt(utils.POWERMAX_PORT_GROUP_NAME_TEMPLATE,
               default='portGroupName',
               help='User defined override for port group name.'),
    cfg.BoolOpt(utils.LOAD_BALANCE,
                default=False,
                help='Enable/disable load balancing for a PowerMax backend.'),
    cfg.BoolOpt(utils.LOAD_BALANCE_RT,
                default=False,
                help='Enable/disable real-time performance metrics for Port '
                     'level load balancing for a PowerMax backend.'),
    cfg.StrOpt(utils.PERF_DATA_FORMAT,
               default='Avg',
               help='Performance data format, not applicable for real-time '
                    'metrics. Available options are "avg" and "max".'),
    cfg.IntOpt(utils.LOAD_LOOKBACK,
               default=60,
               help='How far in minutes to look back for diagnostic '
                    'performance metrics in load calculation, minimum of 0 '
                    'maximum of 1440 (24 hours).'),
    cfg.IntOpt(utils.LOAD_LOOKBACK_RT,
               default=1,
               help='How far in minutes to look back for real-time '
                    'performance metrics in load calculation, minimum of 1 '
                    'maximum of 10.'),
    cfg.StrOpt(utils.PORT_GROUP_LOAD_METRIC,
               default='PercentBusy',
               help='Metric used for port group load calculation.'),
    cfg.StrOpt(utils.PORT_LOAD_METRIC,
               default='PercentBusy',
               help='Metric used for port load calculation.')]


CONF.register_opts(powermax_opts, group=configuration.SHARED_CONF_GROUP)


class PowerMaxCommon(object):
    """Common class for Rest based PowerMax volume drivers.

    This common class is for Dell EMC PowerMax volume drivers
    based on UniSphere Rest API.
    It supports VMAX 3 and VMAX All Flash and PowerMax arrays.

    """
    pool_info = {'backend_name': None,
                 'config_file': None,
                 'arrays_info': {},
                 'max_over_subscription_ratio': None,
                 'reserved_percentage': 0,
                 'replication_enabled': False}

    def __init__(self, prtcl, version, configuration=None,
                 active_backend_id=None):

        self.rest = rest.PowerMaxRest()
        self.utils = utils.PowerMaxUtils()
        self.masking = masking.PowerMaxMasking(prtcl, self.rest)
        self.provision = provision.PowerMaxProvision(self.rest)
        self.volume_metadata = volume_metadata.PowerMaxVolumeMetadata(
            self.rest, version, LOG.isEnabledFor(logging.DEBUG))
        self.migrate = migrate.PowerMaxMigrate(prtcl, self.rest)

        # Configuration/Attributes
        self.protocol = prtcl
        self.configuration = configuration
        self.configuration.append_config_values(powermax_opts)
        self.active_backend_id = active_backend_id
        self.version = version
        self.version_dict = {}
        self.ucode_level = None
        self.next_gen = False
        self.replication_enabled = False
        self.rep_devices = []
        self.failover = True if active_backend_id else False
        self.promotion = False
        self.powermax_array_tag_list = None
        self.powermax_short_host_name_template = None
        self.powermax_port_group_name_template = None
        if active_backend_id == utils.PMAX_FAILOVER_START_ARRAY_PROMOTION:
            self.promotion = True

        # Gather environment info
        self._get_replication_info()
        self._get_u4p_failover_info()
        self._gather_info()
        self._get_performance_config()
        self.rest.validate_unisphere_version()

    def _gather_info(self):
        """Gather the relevant information for update_volume_stats."""
        self._get_attributes_from_config()
        array_info = self.get_attributes_from_cinder_config()
        if array_info is None:
            LOG.error("Unable to get attributes from cinder.conf. Please "
                      "refer to the current online documentation for correct "
                      "configuration and note that the xml file is no "
                      "longer supported.")
        self.rest.set_rest_credentials(array_info)
        if array_info:
            serial_number = array_info['SerialNumber']
            self.array_model, self.next_gen = (
                self.rest.get_array_model_info(serial_number))
            self.ucode_level = self.rest.get_array_ucode_version(serial_number)
            if self.replication_enabled:
                if serial_number in self.replication_targets:
                    msg = (_("The same array serial number (%s) is defined "
                             "for powermax_array and replication_device in "
                             "cinder.conf. Please ensure your "
                             "target_device_id points to a different "
                             "array." % serial_number))
                    LOG.error(msg)
                    raise exception.InvalidConfigurationValue(msg)
        finalarrayinfolist = self._get_slo_workload_combinations(
            array_info)
        self.pool_info['arrays_info'] = finalarrayinfolist

    def _get_attributes_from_config(self):
        """Get relevent details from configuration file."""
        self.interval = self.configuration.safe_get('interval')
        self.retries = self.configuration.safe_get('retries')
        self.powermax_array_tag_list = self.configuration.safe_get(
            utils.POWERMAX_ARRAY_TAG_LIST)
        self.powermax_short_host_name_template = self.configuration.safe_get(
            utils.POWERMAX_SHORT_HOST_NAME_TEMPLATE)
        self.powermax_port_group_name_template = self.configuration.safe_get(
            utils.POWERMAX_PORT_GROUP_NAME_TEMPLATE)
        self.pool_info['backend_name'] = (
            self.configuration.safe_get('volume_backend_name'))
        mosr = volume_utils.get_max_over_subscription_ratio(
            self.configuration.safe_get('max_over_subscription_ratio'), True)
        self.pool_info['max_over_subscription_ratio'] = mosr
        self.pool_info['reserved_percentage'] = (
            self.configuration.safe_get('reserved_percentage'))
        LOG.debug(
            "Updating volume stats on Cinder backend %(backendName)s.",
            {'backendName': self.pool_info['backend_name']})

    def _get_performance_config(self):
        """Gather performance configuration, if provided in cinder.conf."""
        performance_config = {'load_balance': False}
        self.performance = performance.PowerMaxPerformance(
            self.rest, performance_config)

        if self.configuration.safe_get(utils.LOAD_BALANCE):
            LOG.info(
                "Updating performance config for Cinder backend %(be)s.",
                {'be': self.pool_info['backend_name']})
            array_info = self.get_attributes_from_cinder_config()
            self.performance.set_performance_configuration(
                array_info['SerialNumber'], self.configuration)

    def _get_u4p_failover_info(self):
        """Gather Unisphere failover target information, if provided."""

        key_dict = {'san_ip': 'RestServerIp',
                    'san_api_port': 'RestServerPort',
                    'san_login': 'RestUserName',
                    'san_password': 'RestPassword',
                    'driver_ssl_cert_verify': 'SSLVerify',
                    'driver_ssl_cert_path': 'SSLPath'}

        if self.configuration.safe_get('u4p_failover_target'):
            serial_number = self.configuration.safe_get(utils.POWERMAX_ARRAY)
            u4p_targets = self.configuration.safe_get('u4p_failover_target')
            formatted_target_list = list()
            for target in u4p_targets:
                formatted_target = {key_dict[key]: value for key, value in
                                    target.items()}
                formatted_target['SerialNumber'] = serial_number
                try:
                    formatted_target['SSLVerify'] = formatted_target['SSLPath']
                    del formatted_target['SSLPath']
                except KeyError:
                    if formatted_target['SSLVerify'] == 'False':
                        formatted_target['SSLVerify'] = False
                    else:
                        formatted_target['SSLVerify'] = True

                formatted_target_list.append(formatted_target)

            u4p_failover_config = dict()
            u4p_failover_config['u4p_failover_targets'] = formatted_target_list
            u4p_failover_config['u4p_failover_backoff_factor'] = (
                self.configuration.safe_get('u4p_failover_backoff_factor'))
            u4p_failover_config['u4p_failover_retries'] = (
                self.configuration.safe_get('u4p_failover_retries'))
            u4p_failover_config['u4p_failover_timeout'] = (
                self.configuration.safe_get('u4p_failover_timeout'))
            u4p_failover_config['u4p_failover_autofailback'] = (
                self.configuration.safe_get('u4p_failover_autofailback'))
            u4p_failover_config['u4p_primary'] = (
                self.get_attributes_from_cinder_config())

            self.rest.set_u4p_failover_config(u4p_failover_config)
        else:
            LOG.warning("There has been no failover instances of Unisphere "
                        "configured for this instance of Cinder. If your "
                        "primary instance of Unisphere goes down then your "
                        "PowerMax/VMAX will be inaccessible until the "
                        "Unisphere REST API is responsive again.")

    def retest_primary_u4p(self):
        """Retest connection to the primary instance of Unisphere."""
        primary_array_info = self.get_attributes_from_cinder_config()
        temp_conn = rest.PowerMaxRest()
        temp_conn.set_rest_credentials(primary_array_info)
        LOG.debug(
            "Running connection check to primary instance of Unisphere "
            "at %(primary)s", {
                'primary': primary_array_info['RestServerIp']})
        sc, response = temp_conn.request(target_uri='/system/version',
                                         method='GET', u4p_check=True,
                                         request_object=None)
        if sc and int(sc) == 200:
            self._get_u4p_failover_info()
            self.rest.set_rest_credentials(primary_array_info)
            self.rest.u4p_in_failover = False
            LOG.info("Connection to primary instance of Unisphere at "
                     "%(primary)s restored, available failover instances of "
                     "Unisphere reset to default.", {
                         'primary': primary_array_info['RestServerIp']})
        else:
            LOG.debug(
                "Connection check to primary instance of Unisphere at "
                "%(primary)s failed, maintaining session with backup "
                "instance of Unisphere at %(bu_in_use)s", {
                    'primary': primary_array_info['RestServerIp'],
                    'bu_in_use': self.rest.base_uri})
        temp_conn.session.close()

    def _get_initiator_check_flag(self):
        """Reads the configuration for initator_check flag.

        :returns:  flag
        """
        return self.configuration.safe_get('initiator_check')

    def _get_replication_info(self):
        """Gather replication information, if provided."""
        self.rep_configs = None
        self.replication_targets = []
        if hasattr(self.configuration, 'replication_device'):
            self.rep_devices = self.configuration.safe_get(
                'replication_device')
        if self.rep_devices:
            if len(self.rep_devices) > 1:
                self.utils.validate_multiple_rep_device(self.rep_devices)
            self.rep_configs = self.utils.get_replication_config(
                self.rep_devices)
            # use self.replication_enabled for update_volume_stats
            self.replication_enabled = True
            self.replication_targets = self.utils.get_replication_targets(
                self.rep_configs)
            LOG.debug("The replication configuration is %(rep_configs)s.",
                      {'rep_configs': self.rep_configs})

            if self.next_gen:
                for rc in self.rep_configs:
                    rc[utils.RDF_CONS_EXEMPT] = True
            else:
                for rc in self.rep_configs:
                    rc[utils.RDF_CONS_EXEMPT] = False

    def _get_slo_workload_combinations(self, array_info):
        """Method to query the array for SLO and Workloads.

        Takes the arrayinfolist object and generates a set which has
        all available SLO & Workload combinations
        :param array_info: the array information
        :returns: finalarrayinfolist
        :raises: VolumeBackendAPIException:
        """
        try:
            upgraded_afa = False
            if self.array_model in utils.VMAX_HYBRID_MODELS:
                sls = deepcopy(utils.HYBRID_SLS)
                wls = deepcopy(utils.HYBRID_WLS)
            elif self.array_model in utils.VMAX_AFA_MODELS:
                wls = deepcopy(utils.AFA_WLS)
                if not self.next_gen:
                    sls = deepcopy(utils.AFA_H_SLS)
                else:
                    sls = deepcopy(utils.AFA_P_SLS)
                    upgraded_afa = True
            elif self.array_model in utils.PMAX_MODELS:
                sls, wls = deepcopy(utils.PMAX_SLS), deepcopy(utils.PMAX_WLS)
            else:
                raise exception.VolumeBackendAPIException(
                    message="Unable to determine array model.")

            if self.next_gen:
                LOG.warning(
                    "Workloads have been deprecated for arrays running "
                    "PowerMax OS uCode level 5978 or higher. Any supplied "
                    "workloads will be treated as None values. It is "
                    "recommended to create a new volume type without a "
                    "workload specified.")

            # Add service levels:
            pools = sls
            # Array Specific SL/WL Combos
            pools += (
                ['{}:{}'.format(x, y) for x in sls for y in wls
                 if x.lower() not in ['optimized', 'none']])
            # Add Optimized & None combinations
            pools += (
                ['{}:{}'.format(x, y) for x in ['Optimized', 'NONE', 'None']
                 for y in ['NONE', 'None']])

            if upgraded_afa:
                # Cleanup is required here for service levels that were not
                # present in AFA HyperMax but added for AFA PowerMax, we
                # do not need these SL/WL combinations for backwards
                # compatibility but we do for Diamond SL
                afa_pool = list()
                for p in pools:
                    try:
                        pl = p.split(':')
                        if (pl[0] not in [
                            'Platinum', 'Gold', 'Silver', 'Bronze']) or (
                                pl[1] not in [
                                    'OLTP', 'OLTP_REP', 'DSS', 'DSS_REP']):
                            afa_pool.append(p)
                    except IndexError:
                        # Pool has no workload present
                        afa_pool.append(p)
                pools = afa_pool

            # Build array pool of SL/WL combinations
            array_pool = list()
            for pool in pools:
                _array_info = array_info.copy()
                try:
                    slo, workload = pool.split(':')
                    _array_info['SLO'] = slo
                    _array_info['Workload'] = workload
                except ValueError:
                    _array_info['SLO'] = pool
                array_pool.append(_array_info)
        except Exception as e:
            exception_message = (_(
                "Unable to get the SLO/Workload combinations from the array. "
                "Exception received was %(e)s") % {'e': six.text_type(e)})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        return array_pool

    def create_volume(self, volume):
        """Creates a EMC(PowerMax/VMAX) volume from a storage group.

        :param volume: volume object
        :returns:  model_update - dict
        """
        model_update, rep_driver_data = dict(), dict()

        volume_id = volume.id
        extra_specs = self._initial_setup(volume)

        if 'qos' in extra_specs:
            del extra_specs['qos']

        # Volume_name naming convention is 'OS-UUID'.
        volume_name = self.utils.get_volume_element_name(volume_id)
        volume_size = volume.size

        volume_dict, rep_update, rep_info_dict = self._create_volume(
            volume, volume_name, volume_size, extra_specs)

        if rep_update:
            rep_driver_data = rep_update['replication_driver_data']
            model_update.update(rep_update)

        # Add volume to group
        group_name = self._add_to_group(
            volume, volume_dict['device_id'], volume_name, volume.group_id,
            volume.group, extra_specs, rep_driver_data)

        # Gather Metadata
        model_update.update(
            {'provider_location': six.text_type(volume_dict)})
        model_update = self.update_metadata(
            model_update, volume.metadata, self.get_volume_metadata(
                volume_dict['array'], volume_dict['device_id']))
        if rep_update:
            model_update['metadata']['BackendID'] = extra_specs[
                utils.REP_CONFIG].get(utils.BACKEND_ID, 'None')

        array_tag_list = self.get_tags_of_storage_array(
            extra_specs[utils.ARRAY])

        self.volume_metadata.capture_create_volume(
            volume_dict['device_id'], volume, group_name, volume.group_id,
            extra_specs, rep_info_dict, 'create',
            array_tag_list=array_tag_list)

        LOG.info("Leaving create_volume: %(name)s. Volume dict: %(dict)s.",
                 {'name': volume_name, 'dict': volume_dict})

        return model_update

    def _add_to_group(
            self, volume, device_id, volume_name, group_id, group,
            extra_specs, rep_driver_data=None):
        """Add a volume to a volume group

        :param volume: volume object
        :param device_id: the device id
        :param volume_name: volume name
        :param group_id: the group id
        :param group: group object
        :param extra_specs: extra specifications
        :param rep_driver_data: replication data (optional)
        :returns: group_id - string
        """
        group_name = None
        if group_id is not None:
            if group and (volume_utils.is_group_a_cg_snapshot_type(group)
                          or group.is_replicated):
                extra_specs[utils.FORCE_VOL_EDIT] = True
                group_name = self._add_new_volume_to_volume_group(
                    volume, device_id, volume_name,
                    extra_specs, rep_driver_data)
        return group_name

    def _add_new_volume_to_volume_group(self, volume, device_id, volume_name,
                                        extra_specs, rep_driver_data=None):
        """Add a new volume to a volume group.

        This may also be called after extending a replicated volume.
        :param volume: the volume object
        :param device_id: the device id
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        :param rep_driver_data: the replication driver data, optional
        :returns: group_name string
        """
        self.utils.check_replication_matched(volume, extra_specs)
        group_name = self.provision.get_or_create_volume_group(
            extra_specs[utils.ARRAY], volume.group, extra_specs)
        self.masking.add_volume_to_storage_group(
            extra_specs[utils.ARRAY], device_id,
            group_name, volume_name, extra_specs)
        # Add remote volume to remote group, if required
        if volume.group.is_replicated:
            self.masking.add_remote_vols_to_volume_group(
                volume, volume.group, extra_specs, rep_driver_data)
        return group_name

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        :param volume: volume object
        :param snapshot: snapshot object
        :returns: model_update
        :raises: VolumeBackendAPIException:
        """
        LOG.debug("Entering create_volume_from_snapshot.")
        model_update, rep_info_dict = {}, {}
        extra_specs = self._initial_setup(volume)

        # Check if legacy snapshot
        sourcedevice_id = self._find_device_on_array(
            snapshot, extra_specs)
        from_snapvx = False if sourcedevice_id else True

        clone_dict, rep_update, rep_info_dict = self._create_cloned_volume(
            volume, snapshot, extra_specs, from_snapvx=from_snapvx)
        # Update model with replication session info if applicable
        if rep_update:
            model_update.update(rep_update)

        model_update.update(
            {'provider_location': six.text_type(clone_dict)})
        model_update = self.update_metadata(
            model_update, volume.metadata, self.get_volume_metadata(
                clone_dict['array'], clone_dict['device_id']))
        if rep_update:
            model_update['metadata']['BackendID'] = extra_specs[
                utils.REP_CONFIG].get(utils.BACKEND_ID, 'None')
        array_tag_list = self.get_tags_of_storage_array(
            extra_specs[utils.ARRAY])
        self.volume_metadata.capture_create_volume(
            clone_dict['device_id'], volume, None, None,
            extra_specs, rep_info_dict, 'createFromSnapshot',
            source_snapshot_id=snapshot.id, array_tag_list=array_tag_list)

        return model_update

    def create_cloned_volume(self, clone_volume, source_volume):
        """Creates a clone of the specified volume.

        :param clone_volume: clone volume Object
        :param source_volume: volume object
        :returns: model_update, dict
        """
        model_update, rep_info_dict = {}, {}
        rep_driver_data = None
        extra_specs = self._initial_setup(clone_volume)
        array = extra_specs[utils.ARRAY]
        source_device_id = self._find_device_on_array(
            source_volume, extra_specs)

        self._cleanup_device_snapvx(array, source_device_id, extra_specs)

        clone_dict, rep_update, rep_info_dict = self._create_cloned_volume(
            clone_volume, source_volume, extra_specs)
        # Update model with replication session info if applicable
        if rep_update:
            rep_driver_data = rep_update['replication_driver_data']
            model_update.update(rep_update)

        # Add volume to group
        group_name = self._add_to_group(
            clone_volume, clone_dict['device_id'], clone_volume.name,
            clone_volume.group_id, clone_volume.group, extra_specs,
            rep_driver_data)

        model_update.update(
            {'provider_location': six.text_type(clone_dict)})
        model_update = self.update_metadata(
            model_update, clone_volume.metadata, self.get_volume_metadata(
                clone_dict['array'], clone_dict['device_id']))
        if rep_update:
            model_update['metadata']['BackendID'] = extra_specs[
                utils.REP_CONFIG].get(utils.BACKEND_ID, 'None')
        array_tag_list = self.get_tags_of_storage_array(
            extra_specs[utils.ARRAY])

        self.volume_metadata.capture_create_volume(
            clone_dict['device_id'], clone_volume, group_name,
            source_volume.group_id, extra_specs, rep_info_dict,
            'createFromVolume',
            temporary_snapvx=clone_dict.get('snap_name'),
            source_device_id=clone_dict.get('source_device_id'),
            array_tag_list=array_tag_list)
        return model_update

    def delete_volume(self, volume):
        """Deletes a EMC(PowerMax/VMAX) volume.

        :param volume: volume object
        """
        LOG.info("Deleting Volume: %(volume)s",
                 {'volume': volume.name})
        volume_name = self._delete_volume(volume)
        self.volume_metadata.capture_delete_info(volume)
        LOG.info("Leaving delete_volume: %(volume_name)s.",
                 {'volume_name': volume_name})

    def create_snapshot(self, snapshot, volume):
        """Creates a snapshot.

        :param snapshot: snapshot object
        :param volume: volume Object to create snapshot from
        :returns: dict -- the cloned volume dictionary
        """
        extra_specs = self._initial_setup(volume)
        snapshot_dict, __, __ = self._create_cloned_volume(
            snapshot, volume, extra_specs, is_snapshot=True)

        model_update = {
            'provider_location': six.text_type(snapshot_dict)}
        snapshot_metadata = self.get_snapshot_metadata(
            extra_specs.get('array'), snapshot_dict.get('source_id'),
            snapshot_dict.get('snap_name'))
        model_update = self.update_metadata(
            model_update, snapshot.metadata, snapshot_metadata)
        if snapshot.metadata:
            model_update['metadata'].update(snapshot.metadata)
        snapshot_metadata.update(
            {'snap_display_name': snapshot_dict.get('snap_name')})
        self.volume_metadata.capture_snapshot_info(
            volume, extra_specs, 'createSnapshot', snapshot_metadata)

        return model_update

    def delete_snapshot(self, snapshot, volume):
        """Deletes a snapshot.

        :param snapshot: snapshot object
        :param volume: source volume
        """
        LOG.info("Delete Snapshot: %(snapshotName)s.",
                 {'snapshotName': snapshot.name})
        extra_specs = self._initial_setup(volume)
        sourcedevice_id, snap_name, snap_id_list = self._parse_snap_info(
            extra_specs[utils.ARRAY], snapshot)
        if not sourcedevice_id and not snap_name:
            # Check if legacy snapshot
            sourcedevice_id = self._find_device_on_array(
                snapshot, extra_specs)
            if sourcedevice_id:
                self._delete_volume(snapshot)
            else:
                LOG.info("No snapshot found on the array")
        elif not sourcedevice_id or not snap_name:
            LOG.info("No snapshot found on the array")
        else:
            # Ensure snap has not been recently deleted
            for snap_id in snap_id_list:
                self.provision.delete_volume_snap_check_for_links(
                    extra_specs[utils.ARRAY], snap_name,
                    sourcedevice_id, extra_specs, snap_id)

            LOG.info("Leaving delete_snapshot: %(ssname)s.",
                     {'ssname': snap_name})
        self.volume_metadata.capture_snapshot_info(
            volume, extra_specs, 'deleteSnapshot', None)

    def _remove_members(self, array, volume, device_id,
                        extra_specs, connector, is_multiattach,
                        async_grp=None, host_template=None):
        """This method unmaps a volume from a host.

        Removes volume from the storage group that belongs to a masking view.
        :param array: the array serial number
        :param volume: volume object
        :param device_id: the PowerMax/VMAX volume device id
        :param extra_specs: extra specifications
        :param connector: the connector object
        :param is_multiattach: flag to indicate if this is a multiattach case
        :param async_grp: the name if the async group, if applicable
        """
        volume_name = volume.name
        LOG.debug("Detaching volume %s.", volume_name)
        reset = False if is_multiattach else True
        if is_multiattach:
            storage_group_names = self.rest.get_storage_groups_from_volume(
                array, device_id)
        self.masking.remove_and_reset_members(
            array, volume, device_id, volume_name,
            extra_specs, reset, connector, async_grp=async_grp,
            host_template=host_template)
        if is_multiattach:
            self.masking.return_volume_to_fast_managed_group(
                array, device_id, extra_specs)
            self.migrate.cleanup_staging_objects(
                array, storage_group_names, extra_specs)

    def _unmap_lun(self, volume, connector):
        """Unmaps a volume from the host.

        :param volume: the volume Object
        :param connector: the connector Object
        """
        mv_list, sg_list = None, None
        extra_specs = self._initial_setup(volume)
        rep_config = None
        rep_extra_specs = None
        current_host_occurances = 0
        if 'qos' in extra_specs:
            del extra_specs['qos']
        if self.utils.is_replication_enabled(extra_specs):
            backend_id = self._get_replicated_volume_backend_id(volume)
            rep_config = self.utils.get_rep_config(
                backend_id, self.rep_configs)
            extra_specs[utils.FORCE_VOL_EDIT] = True
            rep_extra_specs = self._get_replication_extra_specs(
                extra_specs, rep_config)
            if self.utils.is_volume_failed_over(volume):
                extra_specs = rep_extra_specs
        volume_name = volume.name
        mgmt_sg_name = None
        LOG.info("Unmap volume: %(volume)s.", {'volume': volume})
        if connector is not None:
            host_name = connector.get('host')
            attachment_list = volume.volume_attachment
            LOG.debug("Volume attachment list: %(atl)s. "
                      "Attachment type: %(at)s",
                      {'atl': attachment_list, 'at': type(attachment_list)})
            try:
                att_list = attachment_list.objects
            except AttributeError:
                att_list = attachment_list
            if att_list is not None:
                host_list = [att.connector['host'] for att in att_list if
                             att is not None and att.connector is not None]
                current_host_occurances = host_list.count(host_name)
        else:
            LOG.warning("Cannot get host name from connector object - "
                        "assuming force-detach.")
            host_name = None

        device_info, is_multiattach = (
            self.find_host_lun_id(volume, host_name, extra_specs))
        if 'hostlunid' not in device_info:
            LOG.info("Volume %s is not mapped. No volume to unmap.",
                     volume_name)
            return
        if current_host_occurances > 1:
            LOG.info("Volume is attached to multiple instances on "
                     "this host. Not removing the volume from the "
                     "masking view.")
        else:
            array = extra_specs[utils.ARRAY]
            if self.utils.does_vol_need_rdf_management_group(extra_specs):
                mgmt_sg_name = self.utils.get_rdf_management_group_name(
                    rep_config)
            self._remove_members(
                array, volume, device_info['device_id'], extra_specs,
                connector, is_multiattach, async_grp=mgmt_sg_name,
                host_template=self.powermax_short_host_name_template)
            if (self.utils.is_metro_device(rep_config, extra_specs) and
                    not self.promotion):
                # Need to remove from remote masking view
                device_info, __ = (self.find_host_lun_id(
                    volume, host_name, extra_specs, rep_extra_specs))
                if 'hostlunid' in device_info:
                    self._remove_members(
                        rep_extra_specs[utils.ARRAY], volume,
                        device_info['device_id'], rep_extra_specs, connector,
                        is_multiattach, async_grp=mgmt_sg_name,
                        host_template=self.powermax_short_host_name_template)
                else:
                    # Make an attempt to clean up initiator group
                    self.masking.attempt_ig_cleanup(
                        connector, self.protocol,
                        rep_extra_specs[utils.ARRAY], True,
                        host_template=self.powermax_short_host_name_template)
        if is_multiattach and LOG.isEnabledFor(logging.DEBUG):
            mv_list, sg_list = (
                self._get_mvs_and_sgs_from_volume(
                    extra_specs[utils.ARRAY],
                    device_info['device_id']))
        self.volume_metadata.capture_detach_info(
            volume, extra_specs, device_info['device_id'], mv_list,
            sg_list)

    def _unmap_lun_promotion(self, volume, connector):
        """Unmaps a volume from the host during promotion.

        :param volume: the volume Object
        :param connector: the connector Object
        """
        extra_specs = self._initial_setup(volume)
        if not self.utils.is_replication_enabled(extra_specs):
            LOG.error('Unable to terminate connections for non-replicated '
                      'volumes during promotion failover. Could not unmap '
                      'volume %s', volume.id)
        else:
            mode = extra_specs[utils.REP_MODE]
            if mode == utils.REP_METRO:
                self._unmap_lun(volume, connector)
            else:
                # During a promotion scenario only Metro volumes will have
                # connections present on their remote volumes.
                loc = ast.literal_eval(volume.provider_location)
                device_id = loc.get('device_id')
                promotion_key = [utils.PMAX_FAILOVER_START_ARRAY_PROMOTION]
                self.volume_metadata.capture_detach_info(
                    volume, extra_specs, device_id, promotion_key,
                    promotion_key)

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns device and connection info.

        The volume may be already mapped, if this is so the deviceInfo tuple
        is returned.  If the volume is not already mapped then we need to
        gather information to either 1. Create an new masking view or 2. Add
        the volume to an existing storage group within an already existing
        maskingview.

        The naming convention is the following:

        .. code-block:: none

         initiator_group_name = OS-<shortHostName>-<shortProtocol>-IG
                              e.g OS-myShortHost-I-IG
         storage_group_name = OS-<shortHostName>-<srpName>-<shortProtocol>-SG
                            e.g OS-myShortHost-SRP_1-I-SG
         port_group_name = OS-<target>-PG  The port_group_name will come from
                         the cinder.conf or as an extra spec on the volume
                         type. These are precreated. If the portGroup does not
                         exist then an error will be returned to the user
         maskingview_name  = OS-<shortHostName>-<srpName>-<shortProtocol>-MV
                           e.g OS-myShortHost-SRP_1-I-MV

        :param volume: volume Object
        :param connector: the connector Object
        :returns: dict -- device_info_dict - device information dict
        """
        LOG.info("Initialize connection: %(vol)s.", {'vol': volume.name})
        extra_specs = self._initial_setup(volume, init_conn=True)
        is_multipath = connector.get('multipath', False)
        rep_config = extra_specs.get(utils.REP_CONFIG)
        rep_extra_specs = self._get_replication_extra_specs(
            extra_specs, rep_config)
        remote_port_group = None
        if (self.utils.is_metro_device(rep_config, extra_specs)
                and not is_multipath and self.protocol.lower() == 'iscsi'):
            exception_message = _(
                "Either multipathing is not correctly/currently "
                "enabled on your system or the volume was created "
                "prior to multipathing being enabled. Please refer "
                "to the online PowerMax Cinder driver documentation "
                "for this release for further details.")
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        if self.utils.is_volume_failed_over(volume):
            extra_specs = rep_extra_specs
        device_info_dict, is_multiattach = (
            self.find_host_lun_id(volume, connector.get('host'), extra_specs,
                                  connector=connector))
        masking_view_dict = self._populate_masking_dict(
            volume, connector, extra_specs)
        masking_view_dict[utils.IS_MULTIATTACH] = is_multiattach

        if self.rest.is_next_gen_array(extra_specs['array']):
            masking_view_dict['workload'] = 'NONE'
            temp_pool = masking_view_dict['storagegroup_name']
            splitPool = temp_pool.split('+')
            if len(splitPool) == 4:
                splitPool[1] = 'NONE'
            masking_view_dict['storagegroup_name'] = '+'.join(splitPool)

        if ('hostlunid' in device_info_dict and
                device_info_dict['hostlunid'] is not None):
            hostlunid = device_info_dict['hostlunid']
            LOG.info("Volume %(volume)s is already mapped to host %(host)s. "
                     "The hostlunid is  %(hostlunid)s.",
                     {'volume': volume.name, 'host': connector['host'],
                      'hostlunid': hostlunid})
            port_group_name = (
                self.get_port_group_from_masking_view(
                    extra_specs[utils.ARRAY],
                    device_info_dict['maskingview']))
            if self.utils.is_metro_device(rep_config, extra_specs):
                remote_info_dict, is_multiattach = (
                    self.find_host_lun_id(volume, connector.get('host'),
                                          extra_specs, rep_extra_specs))
                if remote_info_dict.get('hostlunid') is None:
                    # Need to attach on remote side
                    metro_host_lun, remote_port_group = (
                        self._attach_metro_volume(
                            volume, connector, is_multiattach, extra_specs,
                            rep_extra_specs))
                else:
                    metro_host_lun = remote_info_dict['hostlunid']
                    remote_port_group = self.get_port_group_from_masking_view(
                        rep_extra_specs[utils.ARRAY],
                        remote_info_dict['maskingview'])
                device_info_dict['metro_hostlunid'] = metro_host_lun

        else:
            if is_multiattach and extra_specs[utils.SLO]:
                # Need to move volume to a non-fast managed storagegroup
                # before attach on subsequent host(s)
                masking_view_dict = self.masking.pre_multiattach(
                    extra_specs[utils.ARRAY],
                    masking_view_dict[utils.DEVICE_ID], masking_view_dict,
                    extra_specs)
            device_info_dict, port_group_name = (
                self._attach_volume(
                    volume, connector, extra_specs, masking_view_dict))
            if self.utils.is_metro_device(rep_config, extra_specs):
                # Need to attach on remote side
                metro_host_lun, remote_port_group = self._attach_metro_volume(
                    volume, connector, is_multiattach, extra_specs,
                    rep_extra_specs)
                device_info_dict['metro_hostlunid'] = metro_host_lun
        if self.protocol.lower() == 'iscsi':
            device_info_dict['ip_and_iqn'] = (
                self._find_ip_and_iqns(
                    extra_specs[utils.ARRAY], port_group_name))
            if self.utils.is_metro_device(rep_config, extra_specs):
                device_info_dict['metro_ip_and_iqn'] = (
                    self._find_ip_and_iqns(
                        rep_extra_specs[utils.ARRAY], remote_port_group))
            device_info_dict['is_multipath'] = is_multipath

        array_tag_list = self.get_tags_of_storage_array(
            extra_specs[utils.ARRAY])
        if array_tag_list:
            masking_view_dict['array_tag_list'] = array_tag_list

        if is_multiattach and LOG.isEnabledFor(logging.DEBUG):
            masking_view_dict['mv_list'], masking_view_dict['sg_list'] = (
                self._get_mvs_and_sgs_from_volume(
                    extra_specs[utils.ARRAY],
                    masking_view_dict[utils.DEVICE_ID]))
        elif not is_multiattach and LOG.isEnabledFor(logging.DEBUG):
            masking_view_dict['tag_list'] = self.get_tags_of_storage_group(
                extra_specs[utils.ARRAY], masking_view_dict[utils.SG_NAME])

        self.volume_metadata.capture_attach_info(
            volume, extra_specs, masking_view_dict, connector['host'],
            is_multipath, is_multiattach)

        return device_info_dict

    def get_tags_of_storage_group(self, array, storage_group_name):
        """Get the tag information from a storage group

        :param array: serial number of array
        :param storage_group_name: storage group name

        :returns: tag list
        """
        try:
            storage_group = self.rest.get_storage_group(
                array, storage_group_name)
        except Exception:
            return None
        return storage_group.get('tags')

    def get_tags_of_storage_array(self, array):
        """Get the tag information from an array

        :param array: serial number of array

        :returns: tag list
        """
        tag_name_list = None
        try:
            tag_name_list = self.rest.get_array_tags(array)
        except Exception:
            pass
        return tag_name_list

    def _attach_metro_volume(self, volume, connector, is_multiattach,
                             extra_specs, rep_extra_specs):
        """Helper method to attach a metro volume.

        Metro protected volumes point to two PowerMax/VMAX devices on
        different arrays, which are presented as a single device to the host.
        This method masks the remote device to the host.
        :param volume: the volume object
        :param connector: the connector dict
        :param is_multiattach: flag to indicate if this a multiattach case
        :param extra_specs: the extra specifications
        :param rep_extra_specs: replication extra specifications
        :returns: hostlunid, remote_port_group
        """
        remote_mv_dict = self._populate_masking_dict(
            volume, connector, extra_specs, rep_extra_specs)
        remote_mv_dict[utils.IS_MULTIATTACH] = (
            True if is_multiattach else False)
        if is_multiattach and rep_extra_specs[utils.SLO]:
            # Need to move volume to a non-fast managed sg
            # before attach on subsequent host(s)
            remote_mv_dict = self.masking.pre_multiattach(
                rep_extra_specs[utils.ARRAY], remote_mv_dict[utils.DEVICE_ID],
                remote_mv_dict, rep_extra_specs)
        remote_info_dict, remote_port_group = (
            self._attach_volume(
                volume, connector, extra_specs, remote_mv_dict,
                rep_extra_specs=rep_extra_specs))
        remote_port_group = self.get_port_group_from_masking_view(
            rep_extra_specs[utils.ARRAY], remote_info_dict['maskingview'])
        return remote_info_dict['hostlunid'], remote_port_group

    def _attach_volume(self, volume, connector, extra_specs,
                       masking_view_dict, rep_extra_specs=None):
        """Attach a volume to a host.

        :param volume: the volume object
        :param connector: the connector object
        :param extra_specs: extra specifications
        :param masking_view_dict: masking view information
        :param rep_extra_specs: rep extra specs are passed if metro device
        :returns: dict -- device_info_dict
                  String -- port group name
        :raises: VolumeBackendAPIException
        """
        m_specs = extra_specs if rep_extra_specs is None else rep_extra_specs
        rollback_dict = self.masking.setup_masking_view(
            masking_view_dict[utils.ARRAY], volume,
            masking_view_dict, m_specs)

        # Find host lun id again after the volume is exported to the host.

        device_info_dict, __ = self.find_host_lun_id(
            volume, connector.get('host'), extra_specs, rep_extra_specs)
        if 'hostlunid' not in device_info_dict:
            # Did not successfully attach to host, so a rollback is required.
            error_message = (_("Error Attaching volume %(vol)s. Cannot "
                               "retrieve hostlunid.") % {'vol': volume.id})
            LOG.error(error_message)
            self.masking.check_if_rollback_action_for_masking_required(
                masking_view_dict[utils.ARRAY], volume,
                masking_view_dict[utils.DEVICE_ID], rollback_dict)
            raise exception.VolumeBackendAPIException(
                message=error_message)

        return device_info_dict, rollback_dict[utils.PORTGROUPNAME]

    def terminate_connection(self, volume, connector):
        """Disallow connection from connector.

        :param volume: the volume Object
        :param connector: the connector Object
        """
        volume_name = volume.name
        LOG.info("Terminate connection: %(volume)s.",
                 {'volume': volume_name})
        if self.promotion:
            self._unmap_lun_promotion(volume, connector)
        else:
            self._unmap_lun(volume, connector)

    def extend_volume(self, volume, new_size):
        """Extends an existing volume.

        :param volume: the volume Object
        :param new_size: the new size to increase the volume to
        :raises: VolumeBackendAPIException:
        """
        # Set specific attributes for extend operation
        ex_specs = self._initial_setup(volume)
        array = ex_specs[utils.ARRAY]
        device_id = self._find_device_on_array(volume, ex_specs)
        vol_name = volume.name
        orig_vol_size = volume.size
        rep_enabled = self.utils.is_replication_enabled(ex_specs)
        rdf_grp_no = None
        legacy_extend = False

        # Run validation and capabilities checks
        self._extend_vol_validation_checks(
            array, device_id, vol_name, ex_specs, orig_vol_size, new_size)

        # Get extend workflow dependent on array gen and replication status
        if rep_enabled:
            rep_config = ex_specs[utils.REP_CONFIG]
            rdf_grp_no, __ = self.get_rdf_details(array, rep_config)
            self._validate_rdfg_status(array, ex_specs)
            r1_ode, r1_ode_metro, r2_ode, r2_ode_metro = (
                self._array_ode_capabilities_check(array, rep_config, True))

            if self.next_gen:
                if self.utils.is_metro_device(rep_config, ex_specs):
                    if not r1_ode_metro or not r2_ode or not r2_ode_metro:
                        legacy_extend = True
            else:
                legacy_extend = True

        # Handle the extend process using workflow info from previous steps
        if legacy_extend:
            rep_config = ex_specs[utils.REP_CONFIG]
            if rep_config.get('allow_extend', False):
                LOG.info("Legacy extend volume %(volume)s to %(new_size)d GBs",
                         {'volume': vol_name, 'new_size': int(new_size)})
                self._extend_legacy_replicated_vol(
                    array, volume, device_id, vol_name, new_size, ex_specs,
                    rdf_grp_no)
            else:
                exception_message = (
                    "Extending a replicated volume on this backend is not "
                    "permitted. Please set 'allow_extend:True' in your "
                    "PowerMax replication target_backend configuration.")
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    message=exception_message)
        else:
            LOG.info("ODE extend volume %(volume)s to %(new_size)d GBs",
                     {'volume': vol_name,
                      'new_size': int(new_size)})
            self.provision.extend_volume(
                array, device_id, new_size, ex_specs, rdf_grp_no)

        self.volume_metadata.capture_extend_info(
            volume, new_size, device_id, ex_specs, array)

        LOG.debug("Leaving extend_volume: %(volume_name)s. ",
                  {'volume_name': vol_name})

    def _extend_vol_validation_checks(self, array, device_id, vol_name,
                                      ex_specs, orig_vol_size, new_size):
        """Run validation checks on settings for extend volume operation.

        :param array: the array serial number
        :param device_id: the device id
        :param vol_name: the volume name
        :param ex_specs: extra specifications
        :param orig_vol_size: the original volume size
        :param new_size: the new size the volume should be
        :raises: VolumeBackendAPIException:
        """
        # 1 - Check device exists
        if device_id is None:
            exception_message = (_(
                "Cannot find Volume: %(volume_name)s. Extend operation.  "
                "Exiting....") % {'volume_name': vol_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        # 2 - Check if volume is part of an on-going clone operation or if vol
        # has source snapshots but not next-gen array
        self._cleanup_device_snapvx(array, device_id, ex_specs)
        __, snapvx_src, __ = self.rest.is_vol_in_rep_session(array, device_id)
        if snapvx_src:
            if not self.next_gen:
                exception_message = (
                    _("The volume: %(volume)s is a snapshot source. "
                      "Extending a volume with snapVx snapshots is only "
                      "supported on PowerMax/VMAX from OS version 5978 "
                      "onwards. Exiting...") % {'volume': vol_name})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    message=exception_message)

        # 3 - Check new size is larger than old size
        if int(orig_vol_size) >= int(new_size):
            exception_message = (_(
                "Your original size: %(orig_vol_size)s GB is greater "
                "than or the same as: %(new_size)s GB. Only extend ops are "
                "supported. Exiting...") % {'orig_vol_size': orig_vol_size,
                                            'new_size': new_size})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

    def _array_ode_capabilities_check(self, array, rep_config,
                                      rep_enabled=False):
        """Given an array, check Online Device Expansion (ODE) support.

        :param array: the array serial number
        :param rep_config: the replication configuration
        :param rep_enabled: if replication is enabled for backend
        :returns: r1_ode: (bool) If R1 array supports ODE
        :returns: r1_ode_metro: (bool) If R1 array supports ODE with Metro vols
        :returns: r2_ode: (bool) If R2 array supports ODE
        :returns: r2_ode_metro: (bool) If R2 array supports ODE with Metro vols
        """
        r1_ucode = self.ucode_level.split('.')
        r1_ode, r1_ode_metro = False, False
        r2_ode, r2_ode_metro = False, False

        if self.next_gen:
            r1_ode = True
            if rep_enabled:
                __, r2_array = self.get_rdf_details(array, rep_config)
                r2_ucode = self.rest.get_array_ucode_version(r2_array)
                if int(r1_ucode[2]) > utils.UCODE_5978_ELMSR:
                    r1_ode_metro = True
                    r2_ucode = r2_ucode.split('.')
                    if self.rest.is_next_gen_array(r2_array):
                        r2_ode = True
                        if int(r2_ucode[2]) > utils.UCODE_5978_ELMSR:
                            r2_ode_metro = True

        return r1_ode, r1_ode_metro, r2_ode, r2_ode_metro

    @coordination.synchronized('emc-{rdf_group_no}-rdf')
    def _extend_legacy_replicated_vol(
            self, array, volume, device_id, volume_name, new_size, extra_specs,
            rdf_group_no):
        """Extend a legacy OS volume without Online Device Expansion

        :param array: the array serial number
        :param volume: the volume objcet
        :param device_id: the volume device id
        :param volume_name: the volume name
        :param new_size: the new size the volume should be
        :param extra_specs: extra specifications
        :param rdf_group_no: the RDF group number
        """
        try:
            # Break the RDF device pair relationship and cleanup R2
            LOG.info("Breaking replication relationship...")
            self.break_rdf_device_pair_session(
                array, device_id, volume_name, extra_specs, volume)

            # Extend the R1 volume
            LOG.info("Extending source volume...")
            self.provision.extend_volume(
                array, device_id, new_size, extra_specs)

            # Setup volume replication again for source volume
            LOG.info("Recreating replication relationship...")
            rep_status, __, __, rep_extra_specs, resume_rdf = (
                self.configure_volume_replication(
                    array, volume, device_id, extra_specs))

            # If first/only volume in SG then RDF protect SG
            if rep_status == 'first_vol_in_rdf_group':
                self._protect_storage_group(
                    array, device_id, volume, volume_name, rep_extra_specs)

            # If more than one volume in SG then resume replication
            if resume_rdf:
                self.rest.srdf_resume_replication(
                    array, rep_extra_specs['mgmt_sg_name'],
                    rep_extra_specs['rdf_group_no'], extra_specs)

        except Exception as e:
            exception_message = (_("Error extending volume. Error received "
                                   "was %(e)s") % {'e': e})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

    def update_volume_stats(self):
        """Retrieve stats info."""
        if self.rest.u4p_in_failover and self.rest.u4p_failover_autofailback:
            self.retest_primary_u4p()
        pools = []
        # Dictionary to hold the arrays for which the SRP details
        # have already been queried.
        arrays = {}
        total_capacity_gb = 0
        free_capacity_gb = 0
        provisioned_capacity_gb = 0
        location_info = None
        backend_name = self.pool_info['backend_name']
        max_oversubscription_ratio = (
            self.pool_info['max_over_subscription_ratio'])
        reserved_percentage = self.pool_info['reserved_percentage']
        array_reserve_percent = None
        array_info_list = self.pool_info['arrays_info']
        already_queried = False
        for array_info in array_info_list:
            if self.failover:
                rep_config = self.rep_configs[0]
                array_info = self.get_secondary_stats_info(
                    rep_config, array_info)
            # Add both SLO & Workload name in the pool name
            # Only insert the array details in the dict once
            if array_info['SerialNumber'] not in arrays:
                (location_info, total_capacity_gb, free_capacity_gb,
                 provisioned_capacity_gb,
                 array_reserve_percent) = self._update_srp_stats(array_info)
                arrays[array_info['SerialNumber']] = (
                    [total_capacity_gb, free_capacity_gb,
                     provisioned_capacity_gb, array_reserve_percent])
            else:
                already_queried = True
            try:
                pool_name = ("%(slo)s+%(workload)s+%(srpName)s+%(array)s"
                             % {'slo': array_info['SLO'],
                                'workload': array_info['Workload'],
                                'srpName': array_info['srpName'],
                                'array': array_info['SerialNumber']})
            except KeyError:
                pool_name = ("%(slo)s+%(srpName)s+%(array)s"
                             % {'slo': array_info['SLO'],
                                'srpName': array_info['srpName'],
                                'array': array_info['SerialNumber']})

            if already_queried:
                # The dictionary will only have one key per PowerMax/VMAX
                # Construct the location info
                pool = self._construct_location_info_and_pool(
                    array_info, pool_name, arrays, max_oversubscription_ratio,
                    reserved_percentage)
            else:
                pool = {'pool_name': pool_name,
                        'total_capacity_gb': total_capacity_gb,
                        'free_capacity_gb': free_capacity_gb,
                        'provisioned_capacity_gb': provisioned_capacity_gb,
                        'QoS_support': False,
                        'location_info': location_info,
                        'consistencygroup_support': False,
                        'thin_provisioning_support': True,
                        'thick_provisioning_support': False,
                        'consistent_group_snapshot_enabled': True,
                        'max_over_subscription_ratio':
                            max_oversubscription_ratio,
                        'reserved_percentage': reserved_percentage,
                        'replication_enabled': self.replication_enabled,
                        'group_replication_enabled': self.replication_enabled,
                        'consistent_group_replication_enabled':
                            self.replication_enabled
                        }
                if array_reserve_percent:
                    if isinstance(reserved_percentage, int):
                        if array_reserve_percent > reserved_percentage:
                            pool['reserved_percentage'] = array_reserve_percent
                    else:
                        pool['reserved_percentage'] = array_reserve_percent

            pools.append(pool)
        pools = self.utils.add_legacy_pools(pools)
        if self.promotion:
            primary_array = self.configuration.safe_get('powermax_array')
            pools = self.utils.add_promotion_pools(pools, primary_array)
        data = {'vendor_name': "Dell EMC",
                'driver_version': self.version,
                'storage_protocol': 'unknown',
                'volume_backend_name': backend_name or
                self.__class__.__name__,
                # Use zero capacities here so we always use a pool.
                'total_capacity_gb': 0,
                'free_capacity_gb': 0,
                'provisioned_capacity_gb': 0,
                'reserved_percentage': 0,
                'replication_enabled': self.replication_enabled,
                'replication_targets': self.replication_targets,
                'pools': pools}

        return data

    def _construct_location_info_and_pool(
            self, array_info, pool_name, arrays, max_oversubscription_ratio,
            reserved_percentage):
        """Construct the location info string and the pool dict

        :param array_info: array information dict
        :param pool_name: pool name
        :param arrays: arrays dict
        :param max_oversubscription_ratio: max oversubscription ratio
        :param reserved_percentage: reserved percentage

        :returns: pool - dict
        """
        try:
            temp_location_info = (
                ("%(arrayName)s#%(srpName)s#%(slo)s#%(workload)s"
                 % {'arrayName': array_info['SerialNumber'],
                    'srpName': array_info['srpName'],
                    'slo': array_info['SLO'],
                    'workload': array_info['Workload']}))
        except KeyError:
            temp_location_info = (
                ("%(arrayName)s#%(srpName)s#%(slo)s"
                 % {'arrayName': array_info['SerialNumber'],
                    'srpName': array_info['srpName'],
                    'slo': array_info['SLO']}))

        pool = {'pool_name': pool_name,
                'total_capacity_gb':
                    arrays[array_info['SerialNumber']][0],
                'free_capacity_gb':
                    arrays[array_info['SerialNumber']][1],
                'provisioned_capacity_gb':
                    arrays[array_info['SerialNumber']][2],
                'QoS_support': False,
                'location_info': temp_location_info,
                'thin_provisioning_support': True,
                'thick_provisioning_support': False,
                'consistent_group_snapshot_enabled': True,
                'max_over_subscription_ratio':
                    max_oversubscription_ratio,
                'reserved_percentage': reserved_percentage,
                'replication_enabled': self.replication_enabled,
                'multiattach': True}
        if arrays[array_info['SerialNumber']][3]:
            if reserved_percentage:
                if (arrays[array_info['SerialNumber']][3] >
                        reserved_percentage):
                    pool['reserved_percentage'] = (
                        arrays[array_info['SerialNumber']][3])
            else:
                pool['reserved_percentage'] = (
                    arrays[array_info['SerialNumber']][3])
        return pool

    def _update_srp_stats(self, array_info):
        """Update SRP stats.

        :param array_info: array information
        :returns: location_info
        :returns: totalManagedSpaceGbs
        :returns: remainingManagedSpaceGbs
        :returns: provisionedManagedSpaceGbs
        :returns: array_reserve_percent
        :returns: wlpEnabled
        """
        (totalManagedSpaceGbs, remainingManagedSpaceGbs,
         provisionedManagedSpaceGbs, array_reserve_percent) = (
            self.provision.get_srp_pool_stats(
                array_info['SerialNumber'], array_info))

        LOG.info("Capacity stats for SRP pool %(srpName)s on array "
                 "%(arrayName)s total_capacity_gb=%(total_capacity_gb)lu, "
                 "free_capacity_gb=%(free_capacity_gb)lu, "
                 "provisioned_capacity_gb=%(provisioned_capacity_gb)lu",
                 {'srpName': array_info['srpName'],
                  'arrayName': array_info['SerialNumber'],
                  'total_capacity_gb': totalManagedSpaceGbs,
                  'free_capacity_gb': remainingManagedSpaceGbs,
                  'provisioned_capacity_gb': provisionedManagedSpaceGbs})

        try:
            location_info = ("%(arrayName)s#%(srpName)s#%(slo)s#%(workload)s"
                             % {'arrayName': array_info['SerialNumber'],
                                'srpName': array_info['srpName'],
                                'slo': array_info['SLO'],
                                'workload': array_info['Workload']})
        except KeyError:
            location_info = ("%(arrayName)s#%(srpName)s#%(slo)s"
                             % {'arrayName': array_info['SerialNumber'],
                                'srpName': array_info['srpName'],
                                'slo': array_info['SLO']})

        return (location_info, totalManagedSpaceGbs,
                remainingManagedSpaceGbs, provisionedManagedSpaceGbs,
                array_reserve_percent)

    def _set_config_file_and_get_extra_specs(self, volume,
                                             volume_type_id=None):
        """Given the volume object get the associated volumetype.

        Given the volume object get the associated volumetype and the
        extra specs associated with it.
        Based on the name of the config group, register the config file

        :param volume: the volume object including the volume_type_id
        :param volume_type_id: Optional override of volume.volume_type_id
        :returns: dict -- the extra specs dict
        :returns: dict -- QoS specs
        """
        qos_specs = {}
        extra_specs = self.utils.get_volumetype_extra_specs(
            volume, volume_type_id)
        type_id = volume.volume_type_id
        if type_id:
            res = volume_types.get_volume_type_qos_specs(type_id)
            qos_specs = res['qos_specs']

        # If there are no extra specs then the default case is assumed.
        if extra_specs:
            if extra_specs.get('replication_enabled') == '<is> True':
                extra_specs[utils.IS_RE] = True
                backend_id = self._get_replicated_volume_backend_id(volume)
                rep_config = self.utils.get_rep_config(
                    backend_id, self.rep_configs)
                if rep_config is None:
                    msg = _('Could not determine which rep_device to use '
                            'from cinder.conf')
                    raise exception.VolumeBackendAPIException(msg)
                extra_specs[utils.REP_CONFIG] = rep_config
                if rep_config.get('mode'):
                    extra_specs[utils.REP_MODE] = rep_config['mode']
                if rep_config.get(utils.METROBIAS):
                    extra_specs[utils.METROBIAS] = (
                        rep_config[utils.METROBIAS])

        return extra_specs, qos_specs

    def _get_replicated_volume_backend_id(self, volume):
        """Given a volume, return its rep device backend id.

        :param volume: volume used to retrieve backend id -- volume
        :returns: backend id -- str
        """
        backend_id = utils.BACKEND_ID_LEGACY_REP
        volume_extra_specs = self.utils.get_volumetype_extra_specs(volume)
        if volume_extra_specs:
            volume_backend_id = volume_extra_specs.get(
                utils.REPLICATION_DEVICE_BACKEND_ID)
            if volume_backend_id:
                backend_id = volume_backend_id
        return backend_id

    def _find_device_on_array(self, volume, extra_specs, remote_device=False):
        """Given the volume get the PowerMax/VMAX device Id.

        :param volume: volume object
        :param extra_specs: the extra Specs
        :param remote_device: find remote device for replicated volumes
        :returns: array, device_id
        """
        founddevice_id = None
        volume_name = volume.id
        try:
            name_id = volume._name_id
        except AttributeError:
            name_id = None

        if remote_device:
            loc = volume.replication_driver_data
        else:
            loc = volume.provider_location

        if isinstance(loc, six.string_types):
            name = ast.literal_eval(loc)
            array = extra_specs[utils.ARRAY]
            if name.get('device_id'):
                device_id = name['device_id']
            elif name.get('keybindings'):
                device_id = name['keybindings']['DeviceID']
            else:
                device_id = None
            try:
                founddevice_id = self.rest.check_volume_device_id(
                    array, device_id, volume_name, name_id)
            except exception.VolumeBackendAPIException:
                pass

        if founddevice_id is None:
            LOG.debug("Volume %(volume_name)s not found on the array.",
                      {'volume_name': volume_name})
        else:
            LOG.debug("Volume name: %(volume_name)s  Volume device id: "
                      "%(founddevice_id)s.",
                      {'volume_name': volume_name,
                       'founddevice_id': founddevice_id})

        return founddevice_id

    def find_host_lun_id(self, volume, host, extra_specs,
                         rep_extra_specs=None, connector=None):
        """Given the volume dict find the host lun id for a volume.

        :param volume: the volume dict
        :param host: host from connector (can be None on a force-detach)
        :param extra_specs: the extra specs
        :param rep_extra_specs: rep extra specs, passed in if metro device
        :param connector: connector object can be none.
        :returns: dict -- the data dict
        """
        maskedvols = {}
        is_multiattach = False
        volume_name = volume.name
        device_id = self._find_device_on_array(volume, extra_specs)
        if connector:
            if self.migrate.do_migrate_if_candidate(
                    extra_specs[utils.ARRAY], extra_specs[utils.SRP],
                    device_id, volume, connector):
                LOG.debug("MIGRATE - Successfully migrated from device "
                          "%(dev)s from legacy shared storage groups, "
                          "pre Pike release.",
                          {'dev': device_id})
        if rep_extra_specs:
            rdf_pair_info = self.rest.get_rdf_pair_volume(
                extra_specs[utils.ARRAY], rep_extra_specs['rdf_group_no'],
                device_id)
            device_id = rdf_pair_info.get('remoteVolumeName', None)
            extra_specs = rep_extra_specs

        host_name = self.utils.get_host_name_label(
            host, self.powermax_short_host_name_template) if host else None
        if device_id:
            array = extra_specs[utils.ARRAY]
            # Return only masking views for this host
            host_maskingviews, all_masking_view_list = (
                self._get_masking_views_from_volume(
                    array, device_id, host_name))
            if not host_maskingviews:
                # Backward compatibility if a new template was added to
                # an existing backend.
                host_name = self.utils.get_host_short_name(
                    host) if host else None
                host_maskingviews, all_masking_view_list = (
                    self._get_masking_views_from_volume_for_host(
                        all_masking_view_list, host_name))

            for maskingview in host_maskingviews:
                host_lun_id = self.rest.find_mv_connections_for_vol(
                    array, maskingview, device_id)
                if host_lun_id is not None:
                    devicedict = {'hostlunid': host_lun_id,
                                  'maskingview': maskingview,
                                  'array': array,
                                  'device_id': device_id}
                    maskedvols = devicedict

            if not maskedvols:
                LOG.debug(
                    "Host lun id not found for volume: %(volume_name)s "
                    "with the device id: %(device_id)s on host: %(host)s.",
                    {'volume_name': volume_name,
                     'device_id': device_id, 'host': host_name})
            if len(all_masking_view_list) > len(host_maskingviews):
                other_maskedvols = []
                for maskingview in all_masking_view_list:
                    host_lun_id = self.rest.find_mv_connections_for_vol(
                        array, maskingview, device_id)
                    if host_lun_id is not None:
                        devicedict = {'hostlunid': host_lun_id,
                                      'maskingview': maskingview,
                                      'array': array,
                                      'device_id': device_id}
                        other_maskedvols.append(devicedict)
                if len(other_maskedvols) > 0:
                    LOG.debug("Volume is masked to a different host "
                              "than %(host)s - Live Migration or Multi-Attach "
                              "use case.", {'host': host})
                    is_multiattach = True

        else:
            exception_message = (_("Cannot retrieve volume %(vol)s "
                                   "from the array.") % {'vol': volume_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(exception_message)

        return maskedvols, is_multiattach

    def get_masking_views_from_volume(self, array, volume, device_id, host):
        """Get all masking views from a volume.

        :param array: array serial number
        :param volume: the volume object
        :param device_id: the volume device id
        :param host: the host
        :returns: masking view list, is metro
        """
        is_metro = False
        extra_specs = self._initial_setup(volume)
        mv_list, __ = self._get_masking_views_from_volume(array, device_id,
                                                          host)
        if self.utils.is_metro_device(
                extra_specs.get(utils.REP_CONFIG), extra_specs):
            is_metro = True
        return mv_list, is_metro

    def _get_masking_views_from_volume(self, array, device_id, host):
        """Helper function to retrieve masking view list for a volume.

        :param array: array serial number
        :param device_id: the volume device id
        :param host: the host
        :returns: masking view list, all masking view list
        """
        LOG.debug("Getting masking views from volume")
        mvs, __ = self._get_mvs_and_sgs_from_volume(array, device_id)
        return self._get_masking_views_from_volume_for_host(mvs, host)

    def _get_masking_views_from_volume_for_host(
            self, masking_views, host_name):
        """Check all masking views for host_name

        :param masking_views: list of masking view
        :param host_name: the host name for comparision
        :returns: masking view list, all masking view list
        """
        LOG.debug("Getting masking views from volume for host %(host)s ",
                  {'host': host_name})
        host_masking_view_list, all_masking_view_list = [], []
        for masking_view in masking_views:
            all_masking_view_list.append(masking_view)
            if host_name:
                if host_name.lower() in masking_view.lower():
                    host_masking_view_list.append(masking_view)
        host_masking_view_list = (host_masking_view_list if host_name else
                                  all_masking_view_list)
        return host_masking_view_list, all_masking_view_list

    def _get_mvs_and_sgs_from_volume(self, array, device_id):
        """Helper function to retrieve masking views and storage groups.

        :param array: array serial number
        :param device_id: the volume device id
        :returns: masking view list, storage group list
        """
        final_masking_view_list = []
        storage_group_list = self.rest.get_storage_groups_from_volume(
            array, device_id)
        for sg in storage_group_list:
            masking_view_list = self.rest.get_masking_views_from_storage_group(
                array, sg)
            final_masking_view_list.extend(masking_view_list)
        return final_masking_view_list, storage_group_list

    def _initial_setup(self, volume, volume_type_id=None,
                       init_conn=False):
        """Necessary setup to accumulate the relevant information.

        The volume object has a host in which we can parse the
        config group name. The config group name is the key to our EMC
        configuration file. The emc configuration file contains srp name
        and array name which are mandatory fields.
        :param volume: the volume object -- obj
        :param volume_type_id: optional override of volume.volume_type_id
                               -- str
        :param init_conn: if extra specs are for initialize connection -- bool
        :returns: dict -- extra spec dict
        :raises: VolumeBackendAPIException:
        """
        try:
            array_info = self.get_attributes_from_cinder_config()
            if array_info:
                extra_specs, qos_specs = (
                    self._set_config_file_and_get_extra_specs(
                        volume, volume_type_id))
            else:
                exception_message = (_(
                    "Unable to get corresponding record for srp. Please "
                    "refer to the current online documentation for correct "
                    "configuration and note that the xml file is no longer "
                    "supported."))
                raise exception.VolumeBackendAPIException(
                    message=exception_message)

            extra_specs = self._set_vmax_extra_specs(
                extra_specs, array_info, init_conn)
            if qos_specs and qos_specs.get('consumer') != "front-end":
                extra_specs['qos'] = qos_specs.get('specs')
        except Exception:
            exception_message = (_(
                "Unable to get configuration information necessary to "
                "create a volume: %(errorMessage)s.")
                % {'errorMessage': sys.exc_info()[1]})
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        return extra_specs

    def _populate_masking_dict(self, volume, connector,
                               extra_specs, rep_extra_specs=None):
        """Get all the names of the maskingview and sub-components.

        :param volume: the volume object
        :param connector: the connector object
        :param extra_specs: extra specifications
        :param rep_extra_specs: replication extra specs, if metro volume
        :returns: dict -- a dictionary with masking view information
        """
        masking_view_dict = {}
        volume_name = volume.name
        device_id = self._find_device_on_array(volume, extra_specs)
        if rep_extra_specs is not None:
            rdf_pair_info = self.rest.get_rdf_pair_volume(
                extra_specs[utils.ARRAY], rep_extra_specs['rdf_group_no'],
                device_id)
            device_id = rdf_pair_info.get('remoteVolumeName', None)
            extra_specs = rep_extra_specs
        if not device_id:
            exception_message = (_("Cannot retrieve volume %(vol)s "
                                   "from the array. ") % {'vol': volume_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(exception_message)

        protocol = self.utils.get_short_protocol_type(self.protocol)
        short_host_name = self.utils.get_host_name_label(
            connector['host'], self.powermax_short_host_name_template)
        masking_view_dict[utils.USED_HOST_NAME] = short_host_name

        masking_view_dict[utils.SLO] = extra_specs[utils.SLO]
        masking_view_dict[utils.WORKLOAD] = 'NONE' if self.next_gen else (
            extra_specs[utils.WORKLOAD])
        masking_view_dict[utils.ARRAY] = extra_specs[utils.ARRAY]
        masking_view_dict[utils.SRP] = extra_specs[utils.SRP]
        if not extra_specs[utils.PORTGROUPNAME]:
            LOG.warning("You must supply a valid pre-created port group "
                        "in cinder.conf or as an extra spec. Port group "
                        "cannot be left empty as creating a new masking "
                        "view will fail.")
        masking_view_dict[utils.PORT_GROUP_LABEL] = (
            self.utils.get_port_name_label(
                extra_specs[utils.PORTGROUPNAME],
                self.powermax_port_group_name_template))

        masking_view_dict[utils.PORTGROUPNAME] = (
            extra_specs[utils.PORTGROUPNAME])
        masking_view_dict[utils.INITIATOR_CHECK] = (
            self._get_initiator_check_flag())

        child_sg_name, do_disable_compression, rep_enabled = (
            self.utils.get_child_sg_name(
                short_host_name, extra_specs,
                masking_view_dict[utils.PORT_GROUP_LABEL]))
        masking_view_dict[utils.DISABLECOMPRESSION] = do_disable_compression
        masking_view_dict[utils.IS_RE] = rep_enabled
        mv_prefix = (
            "OS-%(shortHostName)s-%(protocol)s-%(pg)s"
            % {'shortHostName': short_host_name,
               'protocol': protocol,
               'pg': masking_view_dict[utils.PORT_GROUP_LABEL]})

        masking_view_dict[utils.SG_NAME] = child_sg_name

        masking_view_dict[utils.MV_NAME] = ("%(prefix)s-MV"
                                            % {'prefix': mv_prefix})

        masking_view_dict[utils.PARENT_SG_NAME] = ("%(prefix)s-SG"
                                                   % {'prefix': mv_prefix})

        masking_view_dict[utils.IG_NAME] = (
            ("OS-%(shortHostName)s-%(protocol)s-IG"
             % {'shortHostName': short_host_name,
                'protocol': protocol}))
        masking_view_dict[utils.CONNECTOR] = connector
        masking_view_dict[utils.DEVICE_ID] = device_id
        masking_view_dict[utils.VOL_NAME] = volume_name

        return masking_view_dict

    def _create_cloned_volume(
            self, volume, source_volume, extra_specs, is_snapshot=False,
            from_snapvx=False):
        """Create a clone volume from the source volume.

        :param volume: clone volume
        :param source_volume: source of the clone volume
        :param extra_specs: extra specs
        :param is_snapshot: boolean -- Defaults to False
        :param from_snapvx: bool -- Defaults to False
        :returns: dict -- cloneDict the cloned volume dictionary
        :raises: VolumeBackendAPIException:
        """
        clone_name = volume.name
        snap_name = None
        rep_update, rep_info_dict = dict(), dict()
        LOG.info("Create a replica from Volume: Clone Volume: %(clone_name)s "
                 "from Source Volume: %(source_name)s.",
                 {'clone_name': clone_name,
                  'source_name': source_volume.name})

        array = extra_specs[utils.ARRAY]
        is_clone_license = self.rest.is_snapvx_licensed(array)
        if not is_clone_license:
            exception_message = (_(
                "SnapVx feature is not licensed on %(array)s.")
                % {'array': array})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        if from_snapvx:
            source_device_id, snap_name, __ = self._parse_snap_info(
                array, source_volume)
        else:
            source_device_id = self._find_device_on_array(
                source_volume, extra_specs)
        if not source_device_id:
            exception_message = (_(
                "Cannot find source device on %(array)s.")
                % {'array': array})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        # Perform any snapvx cleanup if required before creating the clone
        if is_snapshot or from_snapvx:
            self._cleanup_device_snapvx(array, source_device_id, extra_specs)

        if not is_snapshot:
            clone_dict, rep_update, rep_info_dict = self._create_replica(
                array, volume, source_device_id, extra_specs,
                snap_name=snap_name)
        else:
            clone_dict = self._create_snapshot(
                array, volume, source_device_id, extra_specs)

        LOG.debug("Leaving _create_cloned_volume: Volume: "
                  "%(clone_name)s Source Device Id: %(source_name)s ",
                  {'clone_name': clone_name,
                   'source_name': source_device_id})

        return clone_dict, rep_update, rep_info_dict

    def _parse_snap_info(self, array, snapshot):
        """Given a snapshot object, parse the provider_location.

        :param array: the array serial number
        :param snapshot: the snapshot object
        :returns: sourcedevice_id -- str
                  foundsnap_name -- str
                  found_snap_id_list -- list
        """
        foundsnap_name = None
        sourcedevice_id = None
        found_snap_id_list = list()
        volume_name = snapshot.id

        loc = snapshot.provider_location

        if isinstance(loc, six.string_types):
            name = ast.literal_eval(loc)
            try:
                sourcedevice_id = name['source_id']
                snap_name = name['snap_name']
            except KeyError:
                LOG.info("Error retrieving snapshot details. Assuming "
                         "legacy structure of snapshot...")
                return None, None, None
            try:
                snap_detail_list = self.rest.get_volume_snaps(
                    array, sourcedevice_id, snap_name)
                for snap_details in snap_detail_list:
                    foundsnap_name = snap_name
                    found_snap_id_list.append(snap_details.get(
                        'snap_id') if self.rest.is_snap_id else (
                        snap_details.get('generation')))
            except Exception as e:
                LOG.info("Exception in retrieving snapshot: %(e)s.",
                         {'e': e})
                foundsnap_name = None

        if not foundsnap_name or not sourcedevice_id or not found_snap_id_list:
            LOG.debug("Error retrieving snapshot details. "
                      "Snapshot name: %(snap)s",
                      {'snap': volume_name})
        else:
            LOG.debug("Source volume: %(volume_name)s  Snap name: "
                      "%(foundsnap_name)s.",
                      {'volume_name': sourcedevice_id,
                       'foundsnap_name': foundsnap_name,
                       'snap_ids': found_snap_id_list})

        return sourcedevice_id, foundsnap_name, found_snap_id_list

    def _create_snapshot(self, array, snapshot,
                         source_device_id, extra_specs):
        """Create a snap Vx of a volume.

        :param array: the array serial number
        :param snapshot: the snapshot object
        :param source_device_id: the source device id
        :param extra_specs: the extra specifications
        :returns: snap_dict
        """
        clone_name = self.utils.get_volume_element_name(snapshot.id)
        snap_name = self.utils.truncate_string(clone_name, 19)
        try:
            self.provision.create_volume_snapvx(array, source_device_id,
                                                snap_name, extra_specs)
        except Exception as e:
            exception_message = (_("Error creating snap Vx of %(vol)s. "
                                   "Exception received: %(e)s.")
                                 % {'vol': source_device_id,
                                    'e': six.text_type(e)})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        snap_dict = {'snap_name': snap_name, 'source_id': source_device_id}
        return snap_dict

    def _delete_volume(self, volume):
        """Helper function to delete the specified volume.

        Pass in host if is snapshot
        :param volume: volume object to be deleted
        :returns: volume_name (string vol name)
        """
        volume_name = volume.name
        extra_specs = self._initial_setup(volume)

        device_id = self._find_device_on_array(volume, extra_specs)
        if device_id is None:
            LOG.error("Volume %(name)s not found on the array. "
                      "No volume to delete.",
                      {'name': volume_name})
            return volume_name

        array = extra_specs[utils.ARRAY]
        if self.utils.is_replication_enabled(extra_specs):
            self._validate_rdfg_status(array, extra_specs)

        # Check if the volume being deleted is a
        # source or target for copy session
        self._cleanup_device_snapvx(array, device_id, extra_specs)
        # Confirm volume has no more snapshots associated and is not a target
        snapshots = self.rest.get_volume_snapshot_list(array, device_id)
        __, snapvx_target_details = self.rest.find_snap_vx_sessions(
            array, device_id, tgt_only=True)
        if snapshots:
            snapshot_names = ', '.join(
                snap.get('snapshotName') for snap in snapshots)
            raise exception.VolumeBackendAPIException(_(
                'Cannot delete device %s as it currently has the following '
                'active snapshots: %s. Please try again once these snapshots '
                'are no longer active.') % (device_id, snapshot_names))
        if snapvx_target_details:
            source_device = snapvx_target_details.get('source_vol_id')
            snapshot_name = snapvx_target_details.get('snap_name')
            raise exception.VolumeBackendAPIException(_(
                'Cannot delete device %s as it is currently a linked target '
                'of snapshot %s. The source device of this link is %s. '
                'Please try again once this snapshots is no longer '
                'active.') % (device_id, snapshot_name, source_device))

        # Remove from any storage groups and cleanup replication
        self._remove_vol_and_cleanup_replication(
            array, device_id, volume_name, extra_specs, volume)
        # Check if volume is in any storage group
        sg_list = self.rest.get_storage_groups_from_volume(array, device_id)
        if sg_list:
            LOG.error("Device %(device_id)s is in storage group(s) "
                      "%(sg_list)s prior to delete. Delete will fail.",
                      {'device_id': device_id, 'sg_list': sg_list})
        self._delete_from_srp(
            array, device_id, volume_name, extra_specs)
        return volume_name

    def _create_volume(self, volume, volume_name, volume_size, extra_specs):
        """Create a volume.

        :param volume: the volume
        :param volume_name: the volume name
        :param volume_size: the volume size
        :param extra_specs: extra specifications
        :returns: volume_dict, rep_update, rep_info_dict --dict
        """
        # Set Create Volume options
        is_re, rep_mode, storagegroup_name = False, None, None
        rep_info_dict, rep_update = dict(), dict()
        # Get Array details
        array = extra_specs[utils.ARRAY]
        array_model, next_gen = self.rest.get_array_model_info(array)
        if next_gen:
            extra_specs[utils.WORKLOAD] = 'NONE'
        # Verify valid SL/WL combination
        is_valid_slo, is_valid_workload = self.provision.verify_slo_workload(
            array, extra_specs[utils.SLO],
            extra_specs[utils.WORKLOAD], next_gen, array_model)
        if not is_valid_slo or not is_valid_workload:
            exception_message = (_(
                "Either SLO: %(slo)s or workload %(workload)s is invalid. "
                "Examine previous error statement for valid values.")
                % {'slo': extra_specs[utils.SLO],
                   'workload': extra_specs[utils.WORKLOAD]})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        LOG.debug("Create Volume: %(volume)s  Srp: %(srp)s "
                  "Array: %(array)s "
                  "Size: %(size)lu.",
                  {'volume': volume_name,
                   'srp': extra_specs[utils.SRP],
                   'array': array,
                   'size': volume_size})

        do_disable_compression = self.utils.is_compression_disabled(
            extra_specs)

        if self.utils.is_replication_enabled(extra_specs):
            is_re, rep_mode = True, extra_specs['rep_mode']

        storagegroup_name = self.masking.get_or_create_default_storage_group(
            array, extra_specs[utils.SRP], extra_specs[utils.SLO],
            extra_specs[utils.WORKLOAD], extra_specs,
            do_disable_compression, is_re, rep_mode)

        if not is_re:
            volume_dict = self._create_non_replicated_volume(
                array, volume, volume_name, storagegroup_name,
                volume_size, extra_specs)
        else:
            volume_dict, rep_update, rep_info_dict = (
                self._create_replication_enabled_volume(
                    array, volume, volume_name, volume_size, extra_specs,
                    storagegroup_name, rep_mode))

        # Compare volume ID against identifier on array. Update if needed.
        # This can occur in cases where multiple edits are occurring at once.
        found_device_id = self.rest.find_volume_device_id(array, volume_name)
        returning_device_id = volume_dict['device_id']
        if found_device_id != returning_device_id:
            volume_dict['device_id'] = found_device_id

        return volume_dict, rep_update, rep_info_dict

    @coordination.synchronized("emc-nonrdf-vol-{storagegroup_name}-{array}")
    def _create_non_replicated_volume(
            self, array, volume, volume_name, storagegroup_name, volume_size,
            extra_specs):
        """Create a volume without replication enabled

        :param array: the primary array -- string
        :param volume: the volume -- dict
        :param volume_name: the volume name -- string
        :param storagegroup_name: the storage group name -- string
        :param volume_size: the volume size -- string
        :param extra_specs: extra specifications -- dict
        :return: volume_dict -- dict
        :raises: VolumeBackendAPIException:
        """
        existing_devices = self.rest.get_volumes_in_storage_group(
            array, storagegroup_name)
        try:
            volume_dict = self.provision.create_volume_from_sg(
                array, volume_name, storagegroup_name,
                volume_size, extra_specs, rep_info=None)
            return volume_dict
        except Exception as e:
            try:
                # Attempt cleanup of storage group post exception.
                updated_devices = set(self.rest.get_volumes_in_storage_group(
                    array, storagegroup_name))
                devices_to_delete = [device for device in updated_devices
                                     if device not in existing_devices]
                if devices_to_delete:
                    self._cleanup_non_rdf_volume_create_post_failure(
                        volume, volume_name, extra_specs, devices_to_delete)
                elif not existing_devices:
                    self.rest.delete_storage_group(array, storagegroup_name)
            finally:
                # Pass actual exception that was raised now that cleanup
                # attempt is finished. Mainly VolumeBackendAPIException raised
                # from error status codes returned from the various REST jobs.
                raise e

    @coordination.synchronized('emc-rdf-vol-{storagegroup_name}-{array}')
    def _create_replication_enabled_volume(
            self, array, volume, volume_name, volume_size, extra_specs,
            storagegroup_name, rep_mode):
        """Create a volume with replication enabled

        :param array: the primary array
        :param volume: the volume
        :param volume_name: the volume name
        :param volume_size: the volume size
        :param extra_specs: extra specifications
        :param storagegroup_name: the storage group name
        :param rep_mode: the replication mode
        :returns: volume_dict, rep_update, rep_info_dict --dict
        :raises: VolumeBackendAPIException:
        """
        def _is_first_vol_in_replicated_sg():
            vol_dict = dict()
            first_vol, rep_ex_specs, rep_info, rdfg_empty = (
                self.prepare_replication_details(extra_specs))
            if first_vol:
                vol_dict = self.provision.create_volume_from_sg(
                    array, volume_name, storagegroup_name,
                    volume_size, extra_specs, rep_info)
                rep_vol = deepcopy(vol_dict)
                rep_vol.update({'device_uuid': volume_name,
                                'storage_group': storagegroup_name,
                                'size': volume_size})
                if first_vol and rdfg_empty:
                    # First volume in SG, first volume in RDFG
                    self.srdf_protect_storage_group(
                        extra_specs, rep_ex_specs, rep_vol)
                elif not rdfg_empty and not rep_info:
                    # First volume in SG, not first in RDFG
                    __, __, __, rep_ex_specs, resume_rdf = (
                        self.configure_volume_replication(
                            array, volume, vol_dict['device_id'], extra_specs))
                    if resume_rdf:
                        self.rest.srdf_resume_replication(
                            array, rep_ex_specs['mgmt_sg_name'],
                            rep_ex_specs['rdf_group_no'], extra_specs)

            return first_vol, rep_ex_specs, vol_dict

        existing_devices = self.rest.get_volumes_in_storage_group(
            array, storagegroup_name)
        try:
            is_first_volume, rep_extra_specs, volume_info_dict = (
                _is_first_vol_in_replicated_sg())

            if not is_first_volume:
                self._validate_rdfg_status(array, extra_specs)
                __, rep_extra_specs, rep_info_dict, __ = (
                    self.prepare_replication_details(extra_specs))
                volume_info_dict = self.provision.create_volume_from_sg(
                    array, volume_name, storagegroup_name,
                    volume_size, extra_specs, rep_info_dict)

            rep_vol_dict = deepcopy(volume_info_dict)
            rep_vol_dict.update({'device_uuid': volume_name,
                                 'storage_group': storagegroup_name,
                                 'size': volume_size})

            remote_device_id = self.get_and_set_remote_device_uuid(
                extra_specs, rep_extra_specs, rep_vol_dict)
            rep_vol_dict.update({'remote_device_id': remote_device_id})
            rep_update, rep_info_dict = self.gather_replication_updates(
                extra_specs, rep_extra_specs, rep_vol_dict)

            if rep_mode in [utils.REP_ASYNC, utils.REP_METRO]:
                self._add_volume_to_rdf_management_group(
                    array, volume_info_dict['device_id'], volume_name,
                    rep_extra_specs['array'], remote_device_id,
                    extra_specs)

            return volume_info_dict, rep_update, rep_info_dict
        except Exception as e:
            try:
                # Attempt cleanup of rdfg & storage group post exception
                updated_devices = set(self.rest.get_volumes_in_storage_group(
                    array, storagegroup_name))
                devices_to_delete = [device for device in updated_devices
                                     if device not in existing_devices]
                if devices_to_delete:
                    self._cleanup_rdf_volume_create_post_failure(
                        volume, volume_name, extra_specs, devices_to_delete)
                elif not existing_devices:
                    self.rest.delete_storage_group(array, storagegroup_name)
            finally:
                # Pass actual exception that was raised now that cleanup
                # attempt is finished. Mainly VolumeBackendAPIException raised
                # from error status codes returned from the various REST jobs.
                raise e

    def _set_vmax_extra_specs(self, extra_specs, pool_record,
                              init_conn=False):
        """Set the PowerMax/VMAX extra specs.

        The pool_name extra spec must be set, otherwise a default slo/workload
        will be chosen. The portgroup can either be passed as an extra spec
        on the volume type (e.g. 'storagetype:portgroupname = os-pg1-pg'), or
        can be chosen from a list provided in the cinder.conf

        :param extra_specs: extra specifications -- dict
        :param pool_record: pool record -- dict
        :param: init_conn: if extra specs are for initialize connection -- bool
        :returns: the extra specifications -- dict
        """
        # set extra_specs from pool_record
        extra_specs[utils.SRP] = pool_record['srpName']
        extra_specs[utils.ARRAY] = pool_record['SerialNumber']
        extra_specs[utils.PORTGROUPNAME] = (
            self._select_port_group_for_extra_specs(extra_specs, pool_record,
                                                    init_conn))

        self._validate_storage_group_tag_list(extra_specs)

        extra_specs[utils.INTERVAL] = self.interval
        LOG.debug("The interval is set at: %(intervalInSecs)s.",
                  {'intervalInSecs': self.interval})
        extra_specs[utils.RETRIES] = self.retries
        LOG.debug("Retries are set at: %(retries)s.",
                  {'retries': self.retries})

        # Set pool_name slo and workload
        if 'pool_name' in extra_specs:
            pool_name = extra_specs['pool_name']
            pool_details = pool_name.split('+')
            slo_from_extra_spec = pool_details[0]
            workload_from_extra_spec = pool_details[1]
            # Check if legacy pool chosen
            if (workload_from_extra_spec == pool_record['srpName'] or
                    self.next_gen):
                workload_from_extra_spec = 'NONE'

        elif pool_record.get('ServiceLevel'):
            slo_from_extra_spec = pool_record['ServiceLevel']
            workload_from_extra_spec = pool_record.get('Workload', 'None')
            # If workload is None in cinder.conf, convert to string
            if not workload_from_extra_spec or self.next_gen:
                workload_from_extra_spec = 'NONE'
            LOG.info("Pool_name is not present in the extra_specs "
                     "- using slo/ workload from cinder.conf: %(slo)s/%(wl)s.",
                     {'slo': slo_from_extra_spec,
                      'wl': workload_from_extra_spec})

        else:
            slo_list = self.rest.get_slo_list(
                pool_record['SerialNumber'], self.next_gen, self.array_model)
            if 'Optimized' in slo_list:
                slo_from_extra_spec = 'Optimized'
            elif 'Diamond' in slo_list:
                slo_from_extra_spec = 'Diamond'
            else:
                slo_from_extra_spec = 'None'
            workload_from_extra_spec = 'NONE'
            LOG.warning("Pool_name is not present in the extra_specs "
                        "so no slo/ workload information is present "
                        "using default slo/ workload combination: "
                        "%(slo)s/%(wl)s.",
                        {'slo': slo_from_extra_spec,
                         'wl': workload_from_extra_spec})
        # Standardize slo and workload 'NONE' naming conventions
        if workload_from_extra_spec.lower() == 'none':
            workload_from_extra_spec = 'NONE'
        if slo_from_extra_spec.lower() == 'none':
            slo_from_extra_spec = None
        extra_specs[utils.SLO] = slo_from_extra_spec
        extra_specs[utils.WORKLOAD] = workload_from_extra_spec
        if self.rest.is_compression_capable(extra_specs[utils.ARRAY]):
            if not self.utils.is_compression_disabled(extra_specs):
                extra_specs.pop(utils.DISABLECOMPRESSION, None)
        else:
            extra_specs.pop(utils.DISABLECOMPRESSION, None)

        self._check_and_add_tags_to_storage_array(
            extra_specs[utils.ARRAY], self.powermax_array_tag_list,
            extra_specs)

        LOG.debug("SRP is: %(srp)s, Array is: %(array)s "
                  "SLO is: %(slo)s, Workload is: %(workload)s.",
                  {'srp': extra_specs[utils.SRP],
                   'array': extra_specs[utils.ARRAY],
                   'slo': extra_specs[utils.SLO],
                   'workload': extra_specs[utils.WORKLOAD]})
        if self.version_dict:
            self.volume_metadata.print_pretty_table(self.version_dict)
        else:
            self.version_dict = (
                self.volume_metadata.gather_version_info(
                    extra_specs[utils.ARRAY]))

        return extra_specs

    def _select_port_group_for_extra_specs(self, extra_specs, pool_record,
                                           init_conn=False):
        """Determine Port Group for operation extra specs.

        :param extra_specs: existing extra specs -- dict
        :param pool_record: pool record -- dict
        :param init_conn: if extra specs are for initialize connection -- bool
        :returns: Port Group -- str
        :raises: exception.VolumeBackendAPIException
        """
        port_group = None
        conf_port_groups = pool_record.get(utils.PORT_GROUP, [])
        vt_port_group = extra_specs.get(utils.PORTGROUPNAME, None)

        # Scenario 1: Port Group is set in volume-type extra specs, over-rides
        # any settings in cinder.conf
        if vt_port_group:
            port_group = vt_port_group
            LOG.info("Using Port Group '%(pg)s' from volume-type extra specs.",
                     {'pg': port_group})

        # Scenario 2: Port Group(s) set in cinder.conf and not in volume-type
        elif conf_port_groups:
            # Scenario 2-1: There is only one Port Group defined, no load
            # balance or random selection required
            if len(conf_port_groups) == 1:
                port_group = conf_port_groups[0]
                LOG.info(
                    "Using Port Group '%(pg)s' from cinder.conf backend "
                    "configuration.", {'pg': port_group})

            # Scenario 2-2: Else more than one Port Group in cinder.conf
            else:
                # Scenario 2-2-1: If load balancing is enabled and the extra
                # specs are for initialize_connection() method then use load
                # balance selection
                if init_conn and (
                        self.performance.config.get('load_balance', False)):
                    try:
                        load, metric, port_group = (
                            self.performance.process_port_group_load(
                                extra_specs[utils.ARRAY], conf_port_groups))
                        LOG.info(
                            "Selecting Port Group %(pg)s with %(met)s load of "
                            "%(load)s", {'pg': port_group, 'met': metric,
                                         'load': load})
                    except exception.VolumeBackendAPIException:
                        LOG.error(
                            "There has been a problem calculating Port Group "
                            "load, reverting to default random selection.")
                # Scenario 2-2-2: If the call is not for initialize_connection,
                # load balancing is not enabled, or there was an error while
                # calculating PG load, revert to random PG selection method
                if not port_group:
                    port_group = random.choice(conf_port_groups)

        # Port group not extracted from volume-type or cinder.conf, raise
        if not port_group:
            error_message = (_(
                "Port Group name has not been provided - please configure the "
                "'storagetype:portgroupname' extra spec on the volume type, "
                "or enter a list of Port Groups in the cinder.conf associated "
                "with this backend."))
            LOG.error(error_message)
            raise exception.VolumeBackendAPIException(message=error_message)

        return port_group

    def _validate_storage_group_tag_list(self, extra_specs):
        """Validate the storagetype:storagegrouptags list

        :param extra_specs: the extra specifications
        :raises: VolumeBackendAPIException:
        """
        tag_list = extra_specs.get(utils.STORAGE_GROUP_TAGS)
        if tag_list:
            if not self.utils.verify_tag_list(tag_list.split(',')):
                exception_message = (_(
                    "Unable to get verify "
                    "storagetype:storagegrouptags in the Volume Type. "
                    "Only alpha-numeric, dashes and underscores "
                    "allowed. List values must be separated by commas. "
                    "The number of values must not exceed 8"))
                raise exception.VolumeBackendAPIException(
                    message=exception_message)
            else:
                LOG.info("The tag list %(tag_list)s has been verified.",
                         {'tag_list': tag_list})

    def _validate_array_tag_list(self, array_tag_list):
        """Validate the array tag list

        :param array_tag_list: the array tag list
        :raises: VolumeBackendAPIException:
        """
        if array_tag_list:
            if not self.utils.verify_tag_list(array_tag_list):
                exception_message = (_(
                    "Unable to get verify "
                    "config option powermax_array_tag_list. "
                    "Only alpha-numeric, dashes and underscores "
                    "allowed. List values must be separated by commas. "
                    "The number of values must not exceed 8"))
                raise exception.VolumeBackendAPIException(
                    message=exception_message)
            else:
                LOG.info("The tag list %(tag_list)s has been verified.",
                         {'tag_list': array_tag_list})

    def _delete_from_srp(self, array, device_id, volume_name,
                         extra_specs):
        """Delete from srp.

        :param array: the array serial number
        :param device_id: the device id
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        :raises: VolumeBackendAPIException:
        """
        try:
            LOG.debug("Delete Volume: %(name)s. device_id: %(device_id)s.",
                      {'name': volume_name, 'device_id': device_id})
            self.provision.delete_volume_from_srp(
                array, device_id, volume_name)
        except Exception as e:
            error_message = (_("Failed to delete volume %(volume_name)s. "
                               "Exception received: %(e)s") %
                             {'volume_name': volume_name,
                              'e': six.text_type(e)})
            LOG.error(error_message)
            raise exception.VolumeBackendAPIException(message=error_message)

    def _remove_vol_and_cleanup_replication(
            self, array, device_id, volume_name, extra_specs, volume):
        """Remove a volume from its storage groups and cleanup replication.

        :param array: the array serial number
        :param device_id: the device id
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        :param volume: the volume object
        """
        if volume and volume.migration_status == 'deleting':
            extra_specs = self.utils.get_migration_delete_extra_specs(
                volume, extra_specs, self.rep_configs)
        # Cleanup remote replication
        if self.utils.is_replication_enabled(extra_specs):
            rdf_group_no, __ = self.get_rdf_details(
                array, extra_specs[utils.REP_CONFIG])
            self.cleanup_rdf_device_pair(array, rdf_group_no, device_id,
                                         extra_specs)
        else:
            self.masking.remove_and_reset_members(
                array, volume, device_id, volume_name, extra_specs, False)

    @coordination.synchronized('emc-{rdf_group_no}-rdf')
    def cleanup_rdf_device_pair(self, array, rdf_group_no, device_id,
                                extra_specs):
        """Cleanup replication on a RDF device pair, leave only source volume.

        :param array: the array serial number
        :param rdf_group_no: the rdf group number
        :param device_id: the device id
        :param extra_specs: the extra specifications
        :raises: exception.VolumeBackendAPIException
        """
        resume_replication, rdf_mgmt_cleanup = False, False
        rdf_mgmt_sg, vols_in_mgmt_sg = None, None
        rep_config = extra_specs[utils.REP_CONFIG]
        rep_mode = extra_specs['rep_mode']
        if rep_mode in [utils.REP_METRO, utils.REP_ASYNC]:
            extra_specs[utils.FORCE_VOL_EDIT] = True
        rdf_group_no, remote_array = self.get_rdf_details(array, rep_config)
        rep_extra_specs = self._get_replication_extra_specs(
            extra_specs, rep_config)

        # 1. Get the remote device ID so it can be deleted later
        remote_device = self.rest.get_rdf_pair_volume(
            array, rdf_group_no, device_id)
        remote_device_id = remote_device['remoteVolumeName']
        vol_sg_list = self.rest.get_storage_groups_from_volume(
            array, device_id)

        # 2. If replication mode is async or metro, get RDF mgmt group info and
        # suspend RDFG before proceeding to delete operation
        if rep_mode in [utils.REP_METRO, utils.REP_ASYNC]:
            # Make sure devices are in a valid state before continuing
            self.rest.wait_for_rdf_pair_sync(
                array, rdf_group_no, device_id, rep_extra_specs)
            rdf_mgmt_sg = self.utils.get_rdf_management_group_name(rep_config)

            vols_in_mgmt_sg = self.rest.get_num_vols_in_sg(array, rdf_mgmt_sg)
            if vols_in_mgmt_sg > 1:
                resume_replication = True
            else:
                rdf_mgmt_cleanup = True

            self.rest.srdf_suspend_replication(
                array, rdf_mgmt_sg, rdf_group_no, rep_extra_specs)
        try:
            # 3. Check vol doesnt live in any SGs outside OpenStack managed SGs
            if rdf_mgmt_sg and rdf_mgmt_sg in vol_sg_list:
                vol_sg_list.remove(rdf_mgmt_sg)
            if len(vol_sg_list) > 1:
                exception_message = (_(
                    "There is more than one storage group associated with "
                    "device %(dev)s not including RDF management groups. "
                    "Please check device is not member of non-OpenStack "
                    "managed storage groups") % {'dev': device_id})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(exception_message)
            else:
                vol_src_sg = vol_sg_list[0]

            # 4. Remove device from SG and delete RDFG device pair
            self.rest.srdf_remove_device_pair_from_storage_group(
                array, vol_src_sg, rep_extra_specs['array'], device_id,
                rep_extra_specs)

            # 5. Remove the volume from any additional SGs
            if rdf_mgmt_sg:
                self.rest.remove_vol_from_sg(
                    array, rdf_mgmt_sg, device_id, extra_specs)
                self.rest.remove_vol_from_sg(
                    remote_array, rdf_mgmt_sg, remote_device_id,
                    rep_extra_specs)

            # 6. Delete the r2 volume
            self.rest.delete_volume(remote_array, remote_device_id)

            # 7. Delete the SGs if there are no volumes remaining
            self._cleanup_rdf_storage_groups_post_r2_delete(
                array, remote_array, vol_src_sg, rdf_mgmt_sg, rdf_mgmt_cleanup)

            # 8. Resume replication if RDFG still contains volumes
            if resume_replication:
                self.rest.srdf_resume_replication(
                    array, rdf_mgmt_sg, rep_extra_specs['rdf_group_no'],
                    rep_extra_specs)

            LOG.info('Remote device %(dev)s deleted from RDF Group %(grp)s',
                     {'dev': remote_device_id,
                      'grp': rep_extra_specs['rdf_group_label']})
        except Exception as e:
            # Attempt to resume SRDF groups after exception to avoid leaving
            # them in a suspended state.
            try:
                if rdf_mgmt_sg:
                    self.rest.srdf_resume_replication(
                        array, rdf_mgmt_sg, rdf_group_no, rep_extra_specs,
                        False)
                elif len(vol_sg_list) == 1:
                    self.rest.srdf_resume_replication(
                        array, vol_sg_list[0], rdf_group_no, rep_extra_specs,
                        False)
            except Exception:
                LOG.debug('Could not resume SRDF group after exception '
                          'during cleanup_rdf_device_pair.')
            raise e

    def _cleanup_rdf_storage_groups_post_r2_delete(
            self, array, remote_array, sg_name, rdf_mgmt_sg, rdf_mgmt_cleanup):
        """Cleanup storage groups after a RDF device pair has been deleted.

        :param array: the array serial number
        :param remote_array: the remote array serial number
        :param sg_name: the storage group name
        :param rdf_mgmt_sg: the RDF managment group name
        :param rdf_mgmt_cleanup: is RDF management group cleanup required
        """
        vols_in_sg = self.rest.get_num_vols_in_sg(array, sg_name)
        vols_in_remote_sg = self.rest.get_num_vols_in_sg(remote_array, sg_name)
        if not vols_in_sg:
            parent_sg = self.masking.get_parent_sg_from_child(
                array, sg_name)
            self.rest.delete_storage_group(array, sg_name)
            if not vols_in_remote_sg:
                self.rest.delete_storage_group(remote_array, sg_name)
            if parent_sg:
                vols_in_parent = self.rest.get_num_vols_in_sg(
                    array, parent_sg)
                if not vols_in_parent:
                    mv_name = self.rest.get_masking_views_from_storage_group(
                        array, parent_sg)
                    if mv_name:
                        self.rest.delete_masking_view(array, mv_name)
                    if sg_name != parent_sg:
                        self.rest.delete_storage_group(array, parent_sg)
                        self.rest.delete_storage_group(remote_array,
                                                       parent_sg)
        if rdf_mgmt_cleanup:
            self.rest.delete_storage_group(array, rdf_mgmt_sg)
            self.rest.delete_storage_group(remote_array, rdf_mgmt_sg)

    def get_target_wwns_from_masking_view(
            self, volume, connector):
        """Find target WWNs via the masking view.

        :param volume: volume to be attached
        :param connector: the connector dict
        :returns: list -- the target WWN list
        """
        metro_wwns = []
        host = connector['host']
        short_host_name = self.utils.get_host_name_label(
            host, self.powermax_short_host_name_template) if host else None
        extra_specs = self._initial_setup(volume)

        if self.utils.is_volume_failed_over(volume):
            rep_extra_specs = self._get_replication_extra_specs(
                extra_specs, extra_specs[utils.REP_CONFIG])
            extra_specs = rep_extra_specs
        device_id = self._find_device_on_array(volume, extra_specs)
        target_wwns = self._get_target_wwns_from_masking_view(
            device_id, short_host_name, extra_specs)

        if extra_specs.get(utils.REP_CONFIG) and self.utils.is_metro_device(
                extra_specs[utils.REP_CONFIG], extra_specs):
            rdf_group_no, __ = self.get_rdf_details(
                extra_specs[utils.ARRAY], extra_specs[utils.REP_CONFIG])
            rdf_pair_info = self.rest.get_rdf_pair_volume(
                extra_specs[utils.ARRAY], rdf_group_no, device_id)
            remote_device_id = rdf_pair_info.get('remoteVolumeName', None)
            rep_extra_specs = self._get_replication_extra_specs(
                extra_specs, extra_specs[utils.REP_CONFIG])
            metro_wwns = self._get_target_wwns_from_masking_view(
                remote_device_id, short_host_name, rep_extra_specs)

        return target_wwns, metro_wwns

    def _get_target_wwns_from_masking_view(
            self, device_id, short_host_name, extra_specs):
        """Helper function to get wwns from a masking view.

        :param device_id: the device id
        :param short_host_name: the short host name
        :param extra_specs: the extra specs
        :returns: target wwns -- list
        """
        target_wwns = []
        array = extra_specs[utils.ARRAY]
        masking_view_list, __ = self._get_masking_views_from_volume(
            array, device_id, short_host_name)
        if masking_view_list:
            portgroup = self.get_port_group_from_masking_view(
                array, masking_view_list[0])
            target_wwns = self.rest.get_target_wwns(array, portgroup)
            LOG.info("Target wwns in masking view %(maskingView)s: "
                     "%(targetWwns)s.",
                     {'maskingView': masking_view_list[0],
                      'targetWwns': target_wwns})
        return target_wwns

    def get_port_group_from_masking_view(self, array, maskingview_name):
        """Get the port groups in a masking view.

        :param array: the array serial number
        :param maskingview_name: masking view name
        :returns: port group name
        """
        return self.rest.get_element_from_masking_view(
            array, maskingview_name, portgroup=True)

    def get_initiator_group_from_masking_view(self, array, maskingview_name):
        """Get the initiator group in a masking view.

        :param array: the array serial number
        :param maskingview_name: masking view name
        :returns: initiator group name
        """
        return self.rest.get_element_from_masking_view(
            array, maskingview_name, host=True)

    def get_common_masking_views(self, array, portgroup_name,
                                 initiator_group_name):
        """Get common masking views, if any.

        :param array: the array serial number
        :param portgroup_name: port group name
        :param initiator_group_name: ig name
        :returns: list of masking views
        """
        LOG.debug("Finding Masking Views for port group %(pg)s and %(ig)s.",
                  {'pg': portgroup_name, 'ig': initiator_group_name})
        masking_view_list = self.rest.get_common_masking_views(
            array, portgroup_name, initiator_group_name)
        return masking_view_list

    def _get_iscsi_ip_iqn_port(self, array, port):
        """Get ip and iqn from a virtual director port.

        :param array: the array serial number -- str
        :param port: the director & virtual port on the array -- str
        :returns: ip_and_iqn -- dict
        """
        ip_iqn_list = []
        ip_addresses, iqn = self.rest.get_iscsi_ip_address_and_iqn(
            array, port)
        for ip in ip_addresses:
            physical_port = self.rest.get_ip_interface_physical_port(
                array, port.split(':')[0], ip)
            ip_iqn_list.append({'iqn': iqn, 'ip': ip,
                                'physical_port': physical_port})
        return ip_iqn_list

    def _find_ip_and_iqns(self, array, port_group_name):
        """Find the list of ips and iqns for the ports in a port group.

        :param array: the array serial number -- str
        :param port_group_name: the port group name -- str
        :returns: ip_and_iqn -- list of dicts
        """
        ips_and_iqns = []
        LOG.debug("The portgroup name for iscsiadm is %(pg)s",
                  {'pg': port_group_name})
        ports = self.rest.get_port_ids(array, port_group_name)
        for port in ports:
            ip_and_iqn = self._get_iscsi_ip_iqn_port(array, port)
            ips_and_iqns.extend(ip_and_iqn)
        return ips_and_iqns

    def _create_replica(
            self, array, clone_volume, source_device_id,
            extra_specs, snap_name=None):
        """Create a replica.

        Create replica for source volume, source can be volume or snapshot.
        :param array: the array serial number
        :param clone_volume: the clone volume object
        :param source_device_id: the device ID of the volume
        :param extra_specs: extra specifications
        :param snap_name: the snapshot name - optional
        :returns: int -- return code
        :returns: dict -- cloneDict
        """
        clone_id, target_device_id = clone_volume.id, None
        clone_name = self.utils.get_volume_element_name(clone_id)
        create_snap, copy_mode, rep_extra_specs = False, False, dict()
        volume_dict = self.rest.get_volume(array, source_device_id)
        replication_enabled = self.utils.is_replication_enabled(extra_specs)
        if replication_enabled:
            copy_mode = True
            __, rep_extra_specs, __, __ = (
                self.prepare_replication_details(extra_specs))

        # PowerMax/VMAX supports using a target volume that is bigger than
        # the source volume, so we create the target volume the desired
        # size at this point to avoid having to extend later
        try:
            clone_dict, rep_update, rep_info_dict = self._create_volume(
                clone_volume, clone_name, clone_volume.size, extra_specs)

            target_device_id = clone_dict['device_id']
            if target_device_id:
                clone_volume_dict = self.rest.get_volume(
                    array, target_device_id)
                self.utils.compare_cylinders(
                    volume_dict['cap_cyl'], clone_volume_dict['cap_cyl'])
            LOG.info("The target device id is: %(device_id)s.",
                     {'device_id': target_device_id})
            if not snap_name:
                snap_name = self.utils.get_temp_snap_name(source_device_id)
                create_snap = True
            if replication_enabled:
                if rep_extra_specs[utils.REP_CONFIG]['mode'] in (
                        [utils.REP_ASYNC, utils.REP_METRO]):
                    rep_extra_specs['sg_name'] = (
                        self.utils.get_rdf_management_group_name(
                            rep_extra_specs[utils.REP_CONFIG]))
                self.rest.wait_for_rdf_pair_sync(
                    array, rep_extra_specs['rdf_group_no'], target_device_id,
                    rep_extra_specs)
                self.rest.srdf_suspend_replication(
                    array, rep_extra_specs['sg_name'],
                    rep_extra_specs['rdf_group_no'], rep_extra_specs)
            self.provision.create_volume_replica(
                array, source_device_id, target_device_id,
                snap_name, extra_specs, create_snap, copy_mode)
            if replication_enabled:
                self.rest.rdf_resume_with_retries(array, rep_extra_specs)

        except Exception as e:
            if target_device_id:
                LOG.warning("Create replica failed. Cleaning up the target "
                            "volume. Clone name: %(cloneName)s, Error "
                            "received is %(e)s.",
                            {'cloneName': clone_name, 'e': e})
                self._cleanup_target(
                    array, target_device_id, source_device_id,
                    clone_name, snap_name, extra_specs,
                    target_volume=clone_volume)
                # Re-throw the exception.
            raise
        # add source id and snap_name to the clone dict
        clone_dict['source_device_id'] = source_device_id
        clone_dict['snap_name'] = snap_name
        return clone_dict, rep_update, rep_info_dict

    def _cleanup_target(
            self, array, target_device_id, source_device_id,
            clone_name, snap_name, extra_specs, target_volume=None):
        """Cleanup target volume on failed clone/ snapshot creation.

        :param array: the array serial number
        :param target_device_id: the target device ID
        :param source_device_id: the source device ID
        :param clone_name: the name of the clone volume
        :param snap_name: the snapVX name
        :param extra_specs: the extra specifications
        :param target_volume: the target volume object
        """
        snap_id = self.rest.get_snap_id(array, source_device_id, snap_name)
        snap_session = self.rest.get_sync_session(
            array, source_device_id, snap_name, target_device_id, snap_id)
        if snap_session:
            self.provision.unlink_snapvx_tgt_volume(
                array, target_device_id, source_device_id,
                snap_name, extra_specs, snap_id)
        self._remove_vol_and_cleanup_replication(
            array, target_device_id, clone_name, extra_specs, target_volume)
        self._delete_from_srp(
            array, target_device_id, clone_name, extra_specs)

    def _get_target_source_device(self, array, device_id):
        """Get the source device id of the target.

        :param array: the array serial number
        :param device_id: volume instance
        return source_device_id
        """
        LOG.debug("Getting the source device ID for target device %(tgt)s",
                  {'tgt': device_id})
        source_device_id = None
        snapvx_tgt, __, __ = self.rest.is_vol_in_rep_session(
            array, device_id)
        if snapvx_tgt:
            __, tgt_session = self.rest.find_snap_vx_sessions(
                array, device_id, tgt_only=True)
            source_device_id = tgt_session['source_vol_id']
            LOG.debug("Target %(tgt)s source device %(src)s",
                      {'tgt': device_id, 'src': source_device_id})

        return source_device_id

    @retry(retry_exc_tuple, interval=1, retries=3)
    def _cleanup_device_snapvx(
            self, array, device_id, extra_specs):
        """Perform any snapvx cleanup before creating clones or snapshots

        :param array: the array serial
        :param device_id: the device ID of the volume
        :param extra_specs: extra specifications
        """
        snapvx_tgt, snapvx_src, __ = self.rest.is_vol_in_rep_session(
            array, device_id)

        if snapvx_src or snapvx_tgt:
            @coordination.synchronized("emc-source-{src_device_id}")
            def do_unlink_and_delete_snap(src_device_id):
                src_sessions, tgt_session = self.rest.find_snap_vx_sessions(
                    array, src_device_id)
                if tgt_session:
                    self._unlink_and_delete_temporary_snapshots(
                        tgt_session, array, extra_specs)
                if src_sessions:
                    if not self.rest.is_snap_id:
                        src_sessions.sort(
                            key=lambda k: k['snapid'], reverse=True)
                    for src_session in src_sessions:
                        self._unlink_and_delete_temporary_snapshots(
                            src_session, array, extra_specs)
            do_unlink_and_delete_snap(device_id)

    def _unlink_and_delete_temporary_snapshots(
            self, session, array, extra_specs):
        """Helper for unlinking and deleting temporary snapshot sessions

        :param session: snapvx session
        :param array: the array serial number
        :param extra_specs: extra specifications
        """
        try:
            session_unlinked = self._unlink_snapshot(
                session, array, extra_specs)
            if session_unlinked:
                self._delete_temp_snapshot(session, array)
        except exception.VolumeBackendAPIException as e:
            # Ignore and continue as snapshot has been unlinked
            # successfully with incorrect status code returned
            if ('404' and session['snap_name'] and
                    'does not exist' in six.text_type(e)):
                pass

    def _unlink_snapshot(self, session, array, extra_specs):
        """Helper for unlinking temporary snapshot during cleanup.

        :param session: session that contains snapshot
        :param array: the array serial number
        :param extra_specs: extra specifications
        :return:
        """
        snap_name = session.get('snap_name')
        source = session.get('source_vol_id')
        snap_id = session.get('snapid')

        snap_info = self.rest.get_volume_snap(
            array, source, snap_name, snap_id)
        is_linked = snap_info.get('linkedDevices')

        target, cm_enabled = None, False
        if session.get('target_vol_id'):
            target = session.get('target_vol_id')
            cm_enabled = session.get('copy_mode')

        if target and snap_name and is_linked:
            loop = True if cm_enabled else False
            LOG.debug(
                "Unlinking source from target. Source: %(vol)s, Target: "
                "%(tgt)s, Snap id: %(snapid)s.",
                {'vol': source, 'tgt': target, 'snapid': snap_id})
            self.provision.unlink_snapvx_tgt_volume(
                array, target, source, snap_name, extra_specs, snap_id,
                loop)

        is_unlinked = True
        snap_info = self.rest.get_volume_snap(
            array, source, snap_name, snap_id)
        if snap_info and snap_info.get('linkedDevices'):
            is_unlinked = False
        return is_unlinked

    def _delete_temp_snapshot(self, session, array):
        """Helper for deleting temporary snapshot during cleanup.

        :param session: Session that contains snapshot
        :param array: the array serial number
        """
        snap_name = session.get('snap_name')
        source = session.get('source_vol_id')
        snap_id = session.get('snapid')
        LOG.debug(
            "Deleting temp snapshot if it exists. Snap name is: "
            "%(snap_name)s, Source is: %(source)s, "
            "Snap id: %(snap_id)s.",
            {'snap_name': snap_name, 'source': source,
             'snap_id': snap_id})
        is_legacy = 'EMC_SMI' in snap_name if snap_name else False
        is_temp = (
            utils.CLONE_SNAPSHOT_NAME in snap_name if snap_name else False)
        snap_info = self.rest.get_volume_snap(
            array, source, snap_name, snap_id)
        is_linked = snap_info.get('linkedDevices') if snap_info else False

        # Candidates for deletion:
        # 1. If legacy snapshot with 'EMC_SMI' in snapshot name
        # 2. If snapVX snapshot is temporary
        # 3. Snapshot is unlinked. Call _unlink_snapshot before delete.
        if (is_legacy or is_temp) and not is_linked:
            LOG.debug(
                "Deleting temporary snapshot. Source: %(vol)s, snap name: "
                "%(name)s, snap id: %(snapid)s.", {
                    'vol': source, 'name': snap_name, 'snapid': snap_id})
            self.provision.delete_temp_volume_snap(
                array, snap_name, source, snap_id)

    def manage_existing(self, volume, external_ref):
        """Manages an existing PowerMax/VMAX Volume (import to Cinder).

        Renames the existing volume to match the expected name for the volume.
        Also need to consider things like QoS, Emulation, account/tenant.
        :param volume: the volume object including the volume_type_id
        :param external_ref: reference to the existing volume
        :returns: dict -- model_update
        """
        LOG.info("Beginning manage existing volume process")
        rep_info_dict, resume_rdf, rep_status = dict(), False, None
        rep_model_update, rep_driver_data = dict(), dict()
        rep_extra_specs = dict()
        extra_specs = self._initial_setup(volume)
        array, device_id = self.utils.get_array_and_device_id(
            volume, external_ref)
        volume_id = volume.id

        # Check if the existing volume is valid for cinder management
        orig_vol_name, src_sg = self._check_lun_valid_for_cinder_management(
            array, device_id, volume_id, external_ref)
        # If volume name is not present, then assign the device id as the name
        if not orig_vol_name:
            orig_vol_name = device_id
        LOG.debug("Original volume name %(vol)s and source sg: %(sg_name)s.",
                  {'vol': orig_vol_name, 'sg_name': src_sg})

        # Rename the volume
        volume_name = self.utils.get_volume_element_name(volume_id)
        LOG.debug("Rename volume %(vol)s to %(element_name)s.",
                  {'vol': orig_vol_name,
                   'element_name': volume_name})
        self.rest.rename_volume(array, device_id, volume_name)
        provider_location = {'device_id': device_id, 'array': array}
        model_update = {'provider_location': six.text_type(provider_location)}

        # Set-up volume replication, if enabled
        if self.utils.is_replication_enabled(extra_specs):
            (rep_status, rep_driver_data, rep_info_dict,
             rep_extra_specs, resume_rdf) = (
                self.configure_volume_replication(
                    array, volume, device_id, extra_specs))
            if rep_driver_data:
                rep_model_update = {
                    'replication_status': rep_status,
                    'replication_driver_data': six.text_type(
                        {'device_id': rep_info_dict['target_device_id'],
                         'array': rep_info_dict['remote_array']})}

        try:
            # Add/move volume to default storage group
            self.masking.add_volume_to_default_storage_group(
                array, device_id, volume_name, extra_specs, src_sg=src_sg)
            if rep_status == 'first_vol_in_rdf_group':
                rep_status, rep_driver_data, rep_info_dict = (
                    self._protect_storage_group(
                        array, device_id, volume, volume_name,
                        rep_extra_specs))

        except Exception as e:
            exception_message = (_(
                "Unable to move the volume to the default SG. "
                "Exception received was %(e)s") % {'e': six.text_type(e)})
            LOG.error(exception_message)
            LOG.debug("Rename volume %(vol)s back to %(element_name)s.",
                      {'vol': volume_id, 'element_name': orig_vol_name})
            self.rest.rename_volume(array, device_id, orig_vol_name)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        if resume_rdf:
            self.rest.srdf_resume_replication(
                array, rep_extra_specs['mgmt_sg_name'],
                rep_extra_specs['rdf_group_no'], extra_specs)

        if rep_driver_data:
            rep_model_update = {
                'replication_status': rep_status,
                'replication_driver_data': six.text_type(
                    {'device_id': rep_info_dict['target_device_id'],
                     'array': rep_info_dict['remote_array']})}

        model_update.update(rep_model_update)
        model_update = self.update_metadata(
            model_update, volume.metadata, self.get_volume_metadata(
                array, device_id))

        if rep_model_update:
            target_backend_id = extra_specs.get(
                utils.REPLICATION_DEVICE_BACKEND_ID, 'None')
            model_update['metadata']['BackendID'] = target_backend_id

        self.volume_metadata.capture_manage_existing(
            volume, rep_info_dict, device_id, extra_specs)

        return model_update

    def _protect_storage_group(
            self, array, device_id, volume, volume_name, rep_extra_specs):
        """Enable RDF on a volume after it has been managed into OpenStack.

        :param array: the array serial number
        :param device_id: the device id
        :param volume: the volume object
        :param volume_name: the volume name
        :param rep_extra_specs: replication information dictionary
        :returns: replication status, device pair info, replication info --
                  str, dict, dict
        """

        rdf_group_no = rep_extra_specs['rdf_group_no']
        remote_array = rep_extra_specs['array']
        rep_mode = rep_extra_specs['rep_mode']
        rep_config = rep_extra_specs[utils.REP_CONFIG]
        if rep_mode in [utils.REP_ASYNC, utils.REP_METRO]:
            rep_extra_specs['mgmt_sg_name'] = (
                self.utils.get_rdf_management_group_name(rep_config))
        else:
            rep_extra_specs['mgmt_sg_name'] = None

        sg_list = self.rest.get_storage_groups_from_volume(array, device_id)
        if len(sg_list) == 1:
            sg_name = sg_list[0]
        elif len(sg_list) > 1:
            exception_message = (_(
                "Unable to RDF protect device %(dev)s in OpenStack managed "
                "storage group because it currently exists in one or more "
                "user managed storage groups.") % {'dev': device_id})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(exception_message)

        rep_status, pair_info, r2_device_id = (
            self._post_retype_srdf_protect_storage_group(
                array, sg_name, device_id, volume_name, rep_extra_specs,
                volume))

        target_name = self.utils.get_volume_element_name(volume.id)
        rep_info_dict = self.volume_metadata.gather_replication_info(
            volume.id, 'replication', False,
            rdf_group_no=rdf_group_no, target_name=target_name,
            remote_array=remote_array, target_device_id=r2_device_id,
            replication_status=rep_status, rep_mode=rep_mode,
            rdf_group_label=rep_config['rdf_group_label'],
            target_array_model=rep_extra_specs['target_array_model'],
            mgmt_sg_name=rep_extra_specs['mgmt_sg_name'])

        return rep_status, pair_info, rep_info_dict

    def _check_lun_valid_for_cinder_management(
            self, array, device_id, volume_id, external_ref):
        """Check if a volume is valid for cinder management.

        :param array: the array serial number
        :param device_id: the device id
        :param volume_id: the cinder volume id
        :param external_ref: the external reference
        :returns volume_identifier - name of the volume on PowerMax/VMAX
        :returns sg - the storage group which the LUN belongs to
        :raises: ManageExistingInvalidReference, ManageExistingAlreadyManaged:
        """
        # Ensure the volume exists on the array
        volume_details = self.rest.get_volume(array, device_id)
        if not volume_details:
            msg = (_('Unable to retrieve volume details from array for '
                     'device %(device_id)s') % {'device_id': device_id})
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)
        # Check if volume is FBA emulation
        fba_devices = self.rest.get_volume_list(array, "emulation=FBA")
        if device_id not in fba_devices:
            msg = (_("Unable to import volume %(device_id)s to cinder as it "
                     "is not an FBA volume. Only volumes with an emulation "
                     "type of FBA are supported.")
                   % {'device_id': device_id})
            raise exception.ManageExistingVolumeTypeMismatch(reason=msg)
        volume_identifier = None
        # Check if volume is already cinder managed
        if volume_details.get('volume_identifier'):
            volume_identifier = volume_details['volume_identifier']
            if volume_identifier.startswith(utils.VOLUME_ELEMENT_NAME_PREFIX):
                raise exception.ManageExistingAlreadyManaged(
                    volume_ref=volume_id)
        # Check if the volume is part of multiple SGs and
        # check if the volume is attached by checking if in any masking view.
        storagegrouplist = self.rest.get_storage_groups_from_volume(
            array, device_id)
        if storagegrouplist and len(storagegrouplist) > 1:
            msg = (_("Unable to import volume %(device_id)s to cinder. "
                     "Volume is in multiple SGs.")
                   % {'device_id': device_id})
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)
        sg = None
        if storagegrouplist:
            sg = storagegrouplist[0]
            mvs = self.rest.get_masking_views_from_storage_group(
                array, sg)
            if mvs:
                msg = (_("Unable to import volume %(device_id)s to cinder. "
                         "Volume is in masking view(s): %(mv)s.")
                       % {'device_id': device_id, 'mv': mvs})
                raise exception.ManageExistingInvalidReference(
                    existing_ref=external_ref, reason=msg)

        # Check if there are any replication sessions associated
        # with the volume.
        snapvx_tgt, __, rdf = self.rest.is_vol_in_rep_session(
            array, device_id)
        if snapvx_tgt or rdf:
            msg = (_("Unable to import volume %(device_id)s to cinder. "
                     "It is part of a replication session.")
                   % {'device_id': device_id})
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)
        return volume_identifier, sg

    def manage_existing_get_size(self, volume, external_ref):
        """Return size of an existing PowerMax/VMAX volume to manage_existing.

        :param self: reference to class
        :param volume: the volume object including the volume_type_id
        :param external_ref: reference to the existing volume
        :returns: size of the volume in GB
        """
        LOG.debug("Volume in manage_existing_get_size: %(volume)s.",
                  {'volume': volume})
        array, device_id = self.utils.get_array_and_device_id(
            volume, external_ref)
        # Ensure the volume exists on the array
        volume_details = self.rest.get_volume(array, device_id)
        if not volume_details:
            msg = (_('Unable to retrieve volume details from array for '
                     'device %(device_id)s') % {'device_id': device_id})
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)

        size = float(self.rest.get_size_of_device_on_array(array, device_id))
        if not size.is_integer():
            exception_message = (
                _("Cannot manage existing PowerMax/VMAX volume %(device_id)s "
                  "- it has a size of %(vol_size)s but only whole GB "
                  "sizes are supported. Please extend the "
                  "volume to the nearest GB value before importing.")
                % {'device_id': device_id, 'vol_size': size, })
            LOG.error(exception_message)
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=exception_message)

        LOG.debug("Size of volume %(device_id)s is %(vol_size)s GB.",
                  {'device_id': device_id, 'vol_size': int(size)})
        return int(size)

    def unmanage(self, volume):
        """Export PowerMax/VMAX volume from Cinder.

        Leave the volume intact on the backend array.

        :param volume: the volume object
        """
        volume_name = volume.name
        volume_id = volume.id
        LOG.info("Unmanage volume %(name)s, id=%(id)s",
                 {'name': volume_name, 'id': volume_id})
        extra_specs = self._initial_setup(volume)
        device_id = self._find_device_on_array(volume, extra_specs)
        array = extra_specs['array']
        if device_id is None:
            LOG.error("Cannot find Volume: %(id)s for "
                      "unmanage operation. Exiting...",
                      {'id': volume_id})
        else:
            # Check if volume is snap source
            self._cleanup_device_snapvx(array, device_id, extra_specs)
            snapvx_tgt, snapvx_src, __ = self.rest.is_vol_in_rep_session(
                array, device_id)
            if snapvx_src or snapvx_tgt:
                msg = _(
                    'Cannot unmanage volume %s with device id %s as it is '
                    'busy. Please either wait until all temporary snapshot '
                    'have expired or manually unlink and terminate any '
                    'remaining temporary sessions when they have been '
                    'fully copied to their targets. Volume is a snapvx '
                    'source: %s. Volume is a snapvx target: %s' %
                    (volume_id, device_id, snapvx_src, snapvx_tgt))
                LOG.error(msg)
                raise exception.VolumeIsBusy(volume.id)
            # Remove volume from any openstack storage groups
            # and remove any replication
            self._remove_vol_and_cleanup_replication(
                extra_specs['array'], device_id,
                volume_name, extra_specs, volume)
            # Rename the volume to volumeId, thus remove the 'OS-' prefix.
            self.rest.rename_volume(
                extra_specs[utils.ARRAY], device_id, volume_id)
            # First check/create the unmanaged sg
            # Don't fail if we fail to create the SG
            try:
                self.provision.create_storage_group(
                    extra_specs[utils.ARRAY], utils.UNMANAGED_SG,
                    extra_specs[utils.SRP], None,
                    None, extra_specs=extra_specs)
            except Exception as e:
                msg = ("Exception creating %(sg)s. "
                       "Exception received was %(e)s."
                       % {'sg': utils.UNMANAGED_SG,
                          'e': six.text_type(e)})
                LOG.warning(msg)
                return
            # Try to add the volume
            self.masking._check_adding_volume_to_storage_group(
                extra_specs[utils.ARRAY], device_id, utils.UNMANAGED_SG,
                volume_id, extra_specs)

    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Manage an existing PowerMax/VMAX Snapshot (import to Cinder).

        Renames the Snapshot to prefix it with OS- to indicate
        it is managed by Cinder

        :param snapshot: the snapshot object
        :param existing_ref: the snapshot name on the backend VMAX
        :raises: VolumeBackendAPIException
        :returns: model update
        """
        volume = snapshot.volume
        extra_specs = self._initial_setup(volume)
        array = extra_specs[utils.ARRAY]
        device_id = self._find_device_on_array(volume, extra_specs)

        try:
            snap_name = existing_ref['source-name']
        except KeyError:
            snap_name = existing_ref['source-id']

        if snapshot.display_name:
            snap_display_name = snapshot.display_name
        else:
            snap_display_name = snapshot.id

        if snap_name.startswith(utils.VOLUME_ELEMENT_NAME_PREFIX):
            exception_message = (
                _("Unable to manage existing Snapshot. Snapshot "
                  "%(snapshot)s is already managed by Cinder.") %
                {'snapshot': snap_name})
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        if self.utils.is_volume_failed_over(volume):
            exception_message = (
                (_("Volume %(name)s is failed over from the source volume, "
                   "it is not possible to manage a snapshot of a failed over "
                   "volume.") % {'name': volume.id}))
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        snap_id = self.rest.get_snap_id(array, device_id, snap_name)
        snap_backend_name = self.utils.modify_snapshot_prefix(
            snap_name, manage=True)

        try:
            self.rest.modify_volume_snap(
                array, device_id, device_id, snap_name,
                extra_specs, snap_id=snap_id, rename=True,
                new_snap_name=snap_backend_name)
        except Exception as e:
            exception_message = (
                _("There was an issue managing %(snap_name)s, it was not "
                  "possible to add the OS- prefix. Error Message: %(e)s.")
                % {'snap_name': snap_name, 'e': six.text_type(e)})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        prov_loc = {'source_id': device_id, 'snap_name': snap_backend_name}
        model_update = {
            'display_name': snap_display_name,
            'provider_location': six.text_type(prov_loc)}
        snapshot_metadata = self.get_snapshot_metadata(
            array, device_id, snap_backend_name)
        model_update = self.update_metadata(
            model_update, snapshot.metadata, snapshot_metadata)

        LOG.info("Managing SnapVX Snapshot %(snap_name)s of source "
                 "volume %(device_id)s, OpenStack Snapshot display name: "
                 "%(snap_display_name)s", {
                     'snap_name': snap_name, 'device_id': device_id,
                     'snap_display_name': snap_display_name})
        snapshot_metadata.update({'snap_display_name': snap_display_name})
        self.volume_metadata.capture_snapshot_info(
            volume, extra_specs, 'manageSnapshot', snapshot_metadata)

        return model_update

    def manage_existing_snapshot_get_size(self, snapshot):
        """Return the size of the source volume for manage-existing-snapshot.

        :param snapshot: the snapshot object
        :returns: size of the source volume in GB
        """
        volume = snapshot.volume
        extra_specs = self._initial_setup(volume)
        device_id = self._find_device_on_array(volume, extra_specs)
        return self.rest.get_size_of_device_on_array(
            extra_specs[utils.ARRAY], device_id)

    def unmanage_snapshot(self, snapshot):
        """Export PowerMax/VMAX Snapshot from Cinder.

        Leaves the snapshot intact on the backend VMAX

        :param snapshot: the snapshot object
        :raises: VolumeBackendAPIException
        """
        volume = snapshot.volume
        extra_specs = self._initial_setup(volume)
        array = extra_specs[utils.ARRAY]
        device_id, snap_name, snap_id_list = self._parse_snap_info(
            array, snapshot)

        if len(snap_id_list) != 1:
            exception_message = (_(
                "It is not possible to unmanage snapshot because there "
                "are either multiple or no snapshots associated with "
                "%(snap_name)s.") % {'snap_name': snap_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        if self.utils.is_volume_failed_over(volume):
            exception_message = (
                _("It is not possible to unmanage a snapshot where the "
                  "source volume is failed-over, revert back to source "
                  "PowerMax/VMAX to unmanage snapshot %(snap_name)s")
                % {'snap_name': snap_name})

            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        new_snap_backend_name = self.utils.modify_snapshot_prefix(
            snap_name, unmanage=True)

        try:
            self.rest.modify_volume_snap(
                array, device_id, device_id, snap_name, extra_specs,
                snap_id=snap_id_list[0], rename=True,
                new_snap_name=new_snap_backend_name)
        except Exception as e:
            exception_message = (
                _("There was an issue unmanaging Snapshot, it "
                  "was not possible to remove the OS- prefix. Error "
                  "message is: %(e)s.")
                % {'snap_name': snap_name, 'e': six.text_type(e)})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        LOG.info("Snapshot %(snap_name)s is no longer managed in "
                 "OpenStack but still remains on PowerMax/VMAX source "
                 "%(array_id)s", {'snap_name': snap_name, 'array_id': array})

        LOG.warning("In order to remove the snapshot source volume from "
                    "OpenStack you will need to either delete the linked "
                    "SnapVX snapshot on the array or un-manage the volume "
                    "from Cinder.")

    def get_manageable_volumes(self, marker, limit, offset, sort_keys,
                               sort_dirs):
        """Lists all manageable volumes.

        :param marker: Begin returning volumes that appear later in the volume
                       list than that represented by this reference. This
                       reference should be json like. Default=None.
        :param limit: Maximum number of volumes to return. Default=None.
        :param offset: Number of volumes to skip after marker. Default=None.
        :param sort_keys: Key to sort by, sort by size or reference. Valid
                          keys: size, reference. Default=None.
        :param sort_dirs: Direction to sort by. Valid dirs: asc, desc.
                          Default=None.
        :returns: List of dicts containing all volumes valid for management
        """
        valid_vols = []
        manageable_vols = []
        array = self.pool_info['arrays_info'][0]["SerialNumber"]
        LOG.info("Listing manageable volumes for array %(array_id)s", {
            'array_id': array})
        volumes = self.rest.get_private_volume_list(array)

        # No volumes returned from PowerMax/VMAX
        if not volumes:
            LOG.info("There were no volumes found on the backend "
                     "PowerMax/VMAX. You need to create some volumes before "
                     "they can be managed into Cinder.")
            return manageable_vols

        for device in volumes:
            # Determine if volume is valid for management
            if self.utils.is_volume_manageable(device):
                valid_vols.append(device['volumeHeader'])

        # For all valid vols, extract relevant data for Cinder response
        for vol in valid_vols:
            volume_dict = {'reference': {'source-id': vol['volumeId']},
                           'safe_to_manage': True,
                           'size': int(math.ceil(vol['capGB'])),
                           'reason_not_safe': None, 'cinder_id': None,
                           'extra_info': {
                               'config': vol['configuration'],
                               'emulation': vol['emulationType']}}
            manageable_vols.append(volume_dict)

        # If volume list is populated, perform filtering on user params
        if manageable_vols:
            # If sort keys selected, determine if by size or reference, and
            # direction of sort
            manageable_vols = self._sort_manageable_volumes(
                manageable_vols, marker, limit, offset, sort_keys, sort_dirs)

        return manageable_vols

    def _sort_manageable_volumes(
            self, manageable_vols, marker, limit, offset, sort_keys,
            sort_dirs):
        """Sort manageable volumes.

        :param manageable_vols: Unsort list of dicts
        :param marker: Begin returning volumes that appear later in the volume
                       list than that represented by this reference. This
                       reference should be json like. Default=None.
        :param limit: Maximum number of volumes to return. Default=None.
        :param offset: Number of volumes to skip after marker. Default=None.
        :param sort_keys: Key to sort by, sort by size or reference. Valid
                          keys: size, reference. Default=None.
        :param sort_dirs: Direction to sort by. Valid dirs: asc, desc.
                          Default=None.
        :returns: manageable_vols -Sorted list of dicts
        """
        # If sort keys selected, determine if by size or reference, and
        # direction of sort
        if sort_keys:
            reverse = False
            if sort_dirs:
                if 'desc' in sort_dirs[0]:
                    reverse = True
            if sort_keys[0] == 'size':
                manageable_vols = sorted(manageable_vols,
                                         key=lambda k: k['size'],
                                         reverse=reverse)
            if sort_keys[0] == 'reference':
                manageable_vols = sorted(manageable_vols,
                                         key=lambda k: k['reference'][
                                             'source-id'],
                                         reverse=reverse)

        # If marker provided, return only manageable volumes after marker
        if marker:
            vol_index = None
            for vol in manageable_vols:
                if vol['reference']['source-id'] == marker:
                    vol_index = manageable_vols.index(vol)
            if vol_index:
                manageable_vols = manageable_vols[vol_index:]
            else:
                msg = _("Volume marker not found, please check supplied "
                        "device ID and try again.")
                raise exception.VolumeBackendAPIException(msg)

        # If offset or limit provided, offset or limit result list
        if offset:
            manageable_vols = manageable_vols[offset:]
        if limit:
            manageable_vols = manageable_vols[:limit]
        return manageable_vols

    def get_manageable_snapshots(self, marker, limit, offset, sort_keys,
                                 sort_dirs):
        """Lists all manageable snapshots.

        :param marker: Begin returning volumes that appear later in the volume
                       list than that represented by this reference. This
                       reference should be json like. Default=None.
        :param limit: Maximum number of volumes to return. Default=None.
        :param offset: Number of volumes to skip after marker. Default=None.
        :param sort_keys: Key to sort by, sort by size or reference.
                          Valid keys: size, reference. Default=None.
        :param sort_dirs: Direction to sort by. Valid dirs: asc, desc.
                          Default=None.
        :returns: List of dicts containing all snapshots valid for management
        """
        manageable_snaps = []
        array = self.pool_info['arrays_info'][0]["SerialNumber"]
        LOG.info("Listing manageable snapshots for array %(array_id)s", {
            'array_id': array})
        volumes = self.rest.get_private_volume_list(array)

        # No volumes returned from PowerMax/VMAX
        if not volumes:
            LOG.info("There were no volumes found on the backend "
                     "PowerMax/VMAX. You need to create some volumes "
                     "before a snapshot can be created and managed into "
                     "Cinder.")
            return manageable_snaps

        for device in volumes:
            # Determine if volume is valid for management
            manageable_snaps = self._is_snapshot_valid_for_management(
                manageable_snaps, device)

        # If snapshot list is populated, perform filtering on user params
        if len(manageable_snaps) > 0:
            # Order snapshots by source deviceID and not snapshot name
            manageable_snaps = self._sort_manageable_snapshots(
                manageable_snaps, marker, limit, offset, sort_keys, sort_dirs)

        return manageable_snaps

    def _sort_manageable_snapshots(
            self, manageable_snaps, marker, limit, offset, sort_keys,
            sort_dirs):
        """Sorts manageable snapshots list.

        :param manageable_snaps: unsorted manageable snapshot list
        :param marker: Begin returning volumes that appear later in the volume
                       list than that represented by this reference. This
                       reference should be json like. Default=None.
        :param limit: Maximum number of volumes to return. Default=None.
        :param offset: Number of volumes to skip after marker. Default=None.
        :param sort_keys: Key to sort by, sort by size or reference.
                          Valid keys: size, reference. Default=None.
        :param sort_dirs: Direction to sort by. Valid dirs: asc, desc.
                          Default=None.
        :returns: List of dicts containing all snapshots valid for management
        """
        manageable_snaps = sorted(
            manageable_snaps,
            key=lambda k: k['source_reference']['source-id'])
        # If sort keys selected, determine if by size or reference, and
        # direction of sort
        if sort_keys:
            reverse = False
            if sort_dirs:
                if 'desc' in sort_dirs[0]:
                    reverse = True
            if sort_keys[0] == 'size':
                manageable_snaps = sorted(manageable_snaps,
                                          key=lambda k: k['size'],
                                          reverse=reverse)
            if sort_keys[0] == 'reference':
                manageable_snaps = sorted(manageable_snaps,
                                          key=lambda k: k['reference'][
                                              'source-name'],
                                          reverse=reverse)

        # If marker provided, return only manageable volumes after marker
        if marker:
            snap_index = None
            for snap in manageable_snaps:
                if snap['reference']['source-name'] == marker:
                    snap_index = manageable_snaps.index(snap)
            if snap_index:
                manageable_snaps = manageable_snaps[snap_index:]
            else:
                msg = (_("Snapshot marker %(marker)s not found, marker "
                         "provided must be a valid PowerMax/VMAX "
                         "snapshot ID") %
                       {'marker': marker})
                raise exception.VolumeBackendAPIException(msg)

        # If offset or limit provided, offset or limit result list
        if offset:
            manageable_snaps = manageable_snaps[offset:]
        if limit:
            manageable_snaps = manageable_snaps[:limit]
        return manageable_snaps

    def _is_snapshot_valid_for_management(self, manageable_snaps, device):
        """check if snapshot is valid for management

        :param manageable_snaps: list of manageable snapshots
        :param device: the source device

        :returns: List of dicts containing all snapshots valid for management
        """
        if self.utils.is_snapshot_manageable(device):
            # Snapshot valid, extract relevant snap info
            snap_info = device['timeFinderInfo']['snapVXSession'][0][
                'srcSnapshotGenInfo'][0]['snapshotHeader']
            # Convert timestamp to human readable format
            human_timestamp = time.strftime(
                "%Y/%m/%d, %H:%M:%S", time.localtime(
                    float(six.text_type(
                        snap_info['timestamp'])[:-3])))
            # If TTL is set, convert value to human readable format
            if int(snap_info['timeToLive']) > 0:
                human_ttl_timestamp = time.strftime(
                    "%Y/%m/%d, %H:%M:%S", time.localtime(
                        float(six.text_type(
                            snap_info['timeToLive']))))
            else:
                human_ttl_timestamp = 'N/A'

            # For all valid snaps, extract relevant data for Cinder
            # response
            snap_dict = {
                'reference': {
                    'source-name': snap_info['snapshotName']},
                'safe_to_manage': True,
                'size': int(
                    math.ceil(device['volumeHeader']['capGB'])),
                'reason_not_safe': None, 'cinder_id': None,
                'extra_info': {
                    'generation': snap_info.get('generation'),
                    'snap_id': snap_info.get('snapid'),
                    'secured': snap_info.get('secured'),
                    'timeToLive': human_ttl_timestamp,
                    'timestamp': human_timestamp},
                'source_reference': {'source-id': snap_info['device']}}
            manageable_snaps.append(snap_dict)
        return manageable_snaps

    def retype(self, volume, new_type, host):
        """Migrate volume to another host using retype.

        :param volume: the volume object including the volume_type_id
        :param new_type: the new volume type.
        :param host: The host dict holding the relevant target(destination)
            information
        :returns: boolean -- True if retype succeeded, False if error
        """
        volume_name = volume.name
        LOG.info("Migrating Volume %(volume)s via retype.",
                 {'volume': volume_name})

        extra_specs = self._initial_setup(volume)
        if self.utils.is_replication_enabled(extra_specs) and self.promotion:
            rep_config = extra_specs.get('rep_config')
            extra_specs = self._get_replication_extra_specs(
                extra_specs, rep_config)

        if not self.utils.is_retype_supported(volume, extra_specs,
                                              new_type['extra_specs'],
                                              self.rep_configs):
            src_mode = extra_specs.get('rep_mode', 'non-replicated')
            LOG.error("It is not possible to perform host-assisted retype "
                      "from %(src_mode)s to Metro replication type whilst the "
                      "volume is attached to a host. To perform this "
                      "operation please first detach the volume.",
                      {'src_mode': src_mode})
            return False

        device_id = self._find_device_on_array(volume, extra_specs)
        if device_id is None:
            LOG.error("Volume %(name)s not found on the array. "
                      "No volume to migrate using retype.",
                      {'name': volume_name})
            return False

        return self._slo_workload_migration(device_id, volume, host,
                                            volume_name, new_type, extra_specs)

    def _slo_workload_migration(self, device_id, volume, host,
                                volume_name, new_type, extra_specs):
        """Migrate from SLO/Workload combination to another.

        :param device_id: the volume device id
        :param volume: the volume object
        :param host: the host dict
        :param volume_name: the name of the volume
        :param new_type: the type to migrate to
        :param extra_specs: extra specifications
        :returns: boolean -- True if migration succeeded, False if error.
        """
        do_change_compression = False
        # Check if old type and new type have different replication types
        do_change_replication = self.utils.change_replication(
            extra_specs, new_type[utils.EXTRA_SPECS])
        if self.rest.is_compression_capable(extra_specs[utils.ARRAY]):
            is_compression_disabled = self.utils.is_compression_disabled(
                extra_specs)
            # Check if old type and new type have different compression types
            do_change_compression = (self.utils.change_compression_type(
                is_compression_disabled, new_type))
        is_tgt_rep = self.utils.is_replication_enabled(
            new_type[utils.EXTRA_SPECS])
        is_valid, target_slo, target_workload = (
            self._is_valid_for_storage_assisted_migration(
                device_id, host, extra_specs[utils.ARRAY],
                extra_specs[utils.SRP], volume_name,
                do_change_compression, do_change_replication,
                extra_specs[utils.SLO], extra_specs[utils.WORKLOAD],
                is_tgt_rep))

        if not is_valid:
            # Check if this is multiattach retype case
            do_change_multiattach = self.utils.change_multiattach(
                extra_specs, new_type['extra_specs'])
            if do_change_multiattach and not self.promotion:
                return True
            else:
                LOG.error(
                    "Volume %(name)s is not suitable for storage "
                    "assisted migration using retype.",
                    {'name': volume_name})
                return False
        if (volume.host != host['host'] or do_change_compression
                or do_change_replication):
            LOG.debug(
                "Retype Volume %(name)s from source host %(sourceHost)s "
                "to target host %(targetHost)s. Compression change is %(cc)r. "
                "Replication change is %(rc)s.",
                {'name': volume_name, 'sourceHost': volume.host,
                 'targetHost': host['host'],
                 'cc': do_change_compression, 'rc': do_change_replication})
            return self._migrate_volume(
                extra_specs[utils.ARRAY], volume, device_id,
                extra_specs[utils.SRP], target_slo,
                target_workload, volume_name, new_type, extra_specs)

        return False

    def _migrate_volume(
            self, array, volume, device_id, srp, target_slo,
            target_workload, volume_name, new_type, extra_specs):
        """Migrate from one slo/workload combination to another.

        This requires moving the volume from its current SG to a
        new or existing SG that has the target attributes.
        :param array: the array serial number
        :param volume: the volume object
        :param device_id: the device number
        :param srp: the storage resource pool
        :param target_slo: the target service level
        :param target_workload: the target workload
        :param volume_name: the volume name
        :param new_type: the volume type to migrate to
        :param extra_specs: the extra specifications
        :returns: bool
        """
        orig_mgmt_sg_name = None

        target_extra_specs = dict(new_type['extra_specs'])
        target_extra_specs.update({
            utils.SRP: srp, utils.ARRAY: array, utils.SLO: target_slo,
            utils.WORKLOAD: target_workload,
            utils.INTERVAL: extra_specs[utils.INTERVAL],
            utils.RETRIES: extra_specs[utils.RETRIES]})

        compression_disabled = self.utils.is_compression_disabled(
            target_extra_specs)
        target_extra_specs.update(
            {utils.DISABLECOMPRESSION: compression_disabled})
        (was_rep_enabled, is_rep_enabled, backend_ids_differ, rep_mode,
         target_extra_specs) = (
            self._get_replication_flags(
                extra_specs, target_extra_specs))

        if was_rep_enabled and not self.promotion:
            self._validate_rdfg_status(array, extra_specs)
            orig_mgmt_sg_name = self.utils.get_rdf_management_group_name(
                extra_specs[utils.REP_CONFIG])
        if is_rep_enabled:
            self._validate_rdfg_status(array, target_extra_specs)

        # Data to determine what we need to reset during exception cleanup
        initial_sg_list = self.rest.get_storage_groups_from_volume(
            array, device_id)
        if orig_mgmt_sg_name in initial_sg_list:
            initial_sg_list.remove(orig_mgmt_sg_name)
        rdf_pair_broken, rdf_pair_created, vol_retyped, remote_retyped = (
            False, False, False, False)

        self._perform_snapshot_cleanup(
            array, device_id, was_rep_enabled, is_rep_enabled,
            backend_ids_differ, extra_specs, target_extra_specs)

        try:
            # Scenario 1: Rep -> Non-Rep
            # Scenario 2: Cleanup for Rep -> Diff Rep type
            (model_update, resume_original_sg_dict, rdf_pair_broken,
             resume_original_sg, is_partitioned) = (
                self._prep_rep_to_non_rep(
                    array, device_id, volume_name, volume, was_rep_enabled,
                    is_rep_enabled, backend_ids_differ, extra_specs))

            # Scenario 1: Non-Rep -> Rep
            # Scenario 2: Rep -> Diff Rep type
            (model_update, rdf_pair_created, rep_status, rep_driver_data,
             rep_info_dict, rep_extra_specs, resume_target_sg) = (
                self._prep_non_rep_to_rep(
                    array, device_id, volume, was_rep_enabled,
                    is_rep_enabled, backend_ids_differ, target_extra_specs))

            success, target_sg_name = self._retype_volume(
                array, srp, device_id, volume, volume_name, extra_specs,
                target_slo, target_workload, target_extra_specs)
            vol_retyped = True

            # Volume is first volume in RDFG, SG needs to be protected
            if rep_status == 'first_vol_in_rdf_group':
                volume_name = self.utils.get_volume_element_name(volume.id)
                rep_status, rdf_pair_info, tgt_device_id = (
                    self._post_retype_srdf_protect_storage_group(
                        array, target_sg_name, device_id, volume_name,
                        rep_extra_specs, volume))
                model_update = {
                    'replication_status': rep_status,
                    'replication_driver_data': six.text_type(
                        {'device_id': tgt_device_id,
                         'array': rdf_pair_info['remoteSymmetrixId']})}
                rdf_pair_created = True

            # Scenario: Rep -> Same Rep
            if was_rep_enabled and is_rep_enabled and not backend_ids_differ:
                # No change in replication config, retype remote device
                success = self._retype_remote_volume(
                    array, volume, device_id, volume_name,
                    rep_mode, is_rep_enabled, target_extra_specs)
                remote_retyped = True

            if resume_target_sg:
                self.rest.srdf_resume_replication(
                    array, rep_extra_specs['mgmt_sg_name'],
                    rep_extra_specs['rdf_group_no'], rep_extra_specs)
            if (resume_original_sg and resume_original_sg_dict and
                    not self.promotion):
                self.rest.srdf_resume_replication(
                    resume_original_sg_dict[utils.ARRAY],
                    resume_original_sg_dict[utils.SG_NAME],
                    resume_original_sg_dict[utils.RDF_GROUP_NO],
                    resume_original_sg_dict[utils.EXTRA_SPECS])

            if success:
                model_update = self.update_metadata(
                    model_update, volume.metadata,
                    self.get_volume_metadata(array, device_id))

                if self.promotion:
                    previous_host = volume.get('host')
                    host_details = previous_host.split('+')
                    array_index = len(host_details) - 1
                    srp_index = len(host_details) - 2
                    host_details[array_index] = array
                    host_details[srp_index] = srp
                    updated_host = '+'.join(host_details)
                    model_update['host'] = updated_host
                    if is_partitioned:
                        # Must set these here as offline R1 promotion does
                        # not perform rdf cleanup.
                        model_update[
                            'metadata']['ReplicationEnabled'] = 'False'
                        model_update['metadata']['Configuration'] = 'TDEV'

                target_backend_id = None
                if is_rep_enabled:
                    target_backend_id = target_extra_specs.get(
                        utils.REPLICATION_DEVICE_BACKEND_ID, 'None')
                    model_update['metadata']['BackendID'] = target_backend_id
                if was_rep_enabled and not is_rep_enabled:
                    model_update = self.remove_stale_data(model_update)

                self.volume_metadata.capture_retype_info(
                    volume, device_id, array, srp, target_slo,
                    target_workload, target_sg_name, is_rep_enabled, rep_mode,
                    self.utils.is_compression_disabled(target_extra_specs),
                    target_backend_id)

            return success, model_update
        except Exception as e:
            try:
                self._cleanup_on_migrate_failure(
                    rdf_pair_broken, rdf_pair_created, vol_retyped,
                    remote_retyped, extra_specs, target_extra_specs, volume,
                    volume_name, device_id, initial_sg_list[0])
            except Exception:
                # Don't care what this is, just catch it to prevent exception
                # occurred while handling another exception type stack trace.
                LOG.debug(
                    'Volume migrate cleanup - Could not revert volume to '
                    'previous state post volume migrate exception.')
            finally:
                raise e

    def _get_replication_flags(self, extra_specs, target_extra_specs):
        """Get replication flags from extra specifications.

        :param extra_specs: extra specification -- dict
        :param target_extra_specs: target extra specification -- dict
        :returns: was_rep_enabled -- bool, is_rep_enabled -- bool,
                  backend_ids_differ -- bool, rep_mode -- str,
                  target_extra_specs  -- dict
        """
        rep_mode = None
        was_rep_enabled = self.utils.is_replication_enabled(extra_specs)
        if self.utils.is_replication_enabled(target_extra_specs):
            target_backend_id = target_extra_specs.get(
                utils.REPLICATION_DEVICE_BACKEND_ID,
                utils.BACKEND_ID_LEGACY_REP)
            target_rep_config = self.utils.get_rep_config(
                target_backend_id, self.rep_configs)
            rep_mode = target_rep_config['mode']
            target_extra_specs[utils.REP_MODE] = rep_mode
            target_extra_specs[utils.REP_CONFIG] = target_rep_config
            is_rep_enabled = True
        else:
            is_rep_enabled = False

        backend_ids_differ = False
        if was_rep_enabled and is_rep_enabled:
            curr_backend_id = extra_specs.get(
                utils.REPLICATION_DEVICE_BACKEND_ID,
                utils.BACKEND_ID_LEGACY_REP)
            tgt_backend_id = target_extra_specs.get(
                utils.REPLICATION_DEVICE_BACKEND_ID,
                utils.BACKEND_ID_LEGACY_REP)
            backend_ids_differ = curr_backend_id != tgt_backend_id

        return (was_rep_enabled, is_rep_enabled, backend_ids_differ, rep_mode,
                target_extra_specs)

    def _prep_non_rep_to_rep(
            self, array, device_id, volume, was_rep_enabled,
            is_rep_enabled, backend_ids_differ, target_extra_specs):
        """Prepare for non rep to rep retype.

        :param array: the array serial number -- str
        :param device_id: the device id -- str
        :param volume: the volume object -- objects.Volume
        :param was_rep_enabled: flag -- bool
        :param is_rep_enabled: flag -- bool
        :param backend_ids_differ:  flag -- bool
        :param target_extra_specs: target extra specs -- dict
        :returns: model_update -- dict, rdf_pair_created -- bool,
                  rep_status -- str, rep_driver_data -- dict,
                  rep_info_dict -- dict, rep_extra_specs -- dict,
                  resume_target_sg -- bool
        """
        model_update, rep_status = None, None
        resume_target_sg = False
        rdf_pair_created = False
        rep_driver_data, rep_info_dict = dict(), dict()
        rep_extra_specs = dict()
        if (not was_rep_enabled and is_rep_enabled) or backend_ids_differ:
            (rep_status, rep_driver_data, rep_info_dict,
             rep_extra_specs, resume_target_sg) = (
                self.configure_volume_replication(
                    array, volume, device_id, target_extra_specs))
            if rep_status != 'first_vol_in_rdf_group':
                rdf_pair_created = True
            model_update = {
                'replication_status': rep_status,
                'replication_driver_data': six.text_type(
                    {'device_id': rep_info_dict['target_device_id'],
                     'array': rep_info_dict['remote_array']})}

        return (model_update, rdf_pair_created, rep_status, rep_driver_data,
                rep_info_dict, rep_extra_specs, resume_target_sg)

    def _prep_rep_to_non_rep(
            self, array, device_id, volume_name, volume, was_rep_enabled,
            is_rep_enabled, backend_ids_differ, extra_specs):
        """Preparation for replication to non-replicated.

        :param array: the array serial number -- str
        :param device_id: device_id: the device id -- str
        :param volume_name: the volume name -- str
        :param volume: the volume object -- objects.Volume
        :param was_rep_enabled: flag -- bool
        :param is_rep_enabled: flag -- bool
        :param backend_ids_differ: flag -- bool
        :param extra_specs: extra specs -- dict
        :returns: model_update --dict , resume_original_sg_dict -- dict,
                  rdf_pair_broken -- bool, resume_original_sg -- bool,
                  is_partitioned -- bool
        """
        model_update = dict()
        resume_original_sg_dict = dict()
        rdf_pair_broken = False
        resume_original_sg = False
        is_partitioned = False
        if (was_rep_enabled and not is_rep_enabled) or backend_ids_differ:
            if self.promotion:
                resume_original_sg = False
                rdf_group = extra_specs['rdf_group_no']
                is_partitioned = self._rdf_vols_partitioned(
                    array, [volume], rdf_group)
                if not is_partitioned:
                    self.break_rdf_device_pair_session_promotion(
                        array, device_id, volume_name, extra_specs)
            else:
                rep_extra_specs, resume_original_sg = (
                    self.break_rdf_device_pair_session(
                        array, device_id, volume_name, extra_specs,
                        volume))
            status = (REPLICATION_ERROR if self.promotion else
                      REPLICATION_DISABLED)
            model_update = {
                'replication_status': status,
                'replication_driver_data': None}
            rdf_pair_broken = True
            if resume_original_sg:
                resume_original_sg_dict = {
                    utils.ARRAY: array,
                    utils.SG_NAME: rep_extra_specs['mgmt_sg_name'],
                    utils.RDF_GROUP_NO: rep_extra_specs['rdf_group_no'],
                    utils.EXTRA_SPECS: rep_extra_specs}
        return (model_update, resume_original_sg_dict, rdf_pair_broken,
                resume_original_sg, is_partitioned)

    def _perform_snapshot_cleanup(
            self, array, device_id, was_rep_enabled, is_rep_enabled,
            backend_ids_differ, extra_specs, target_extra_specs):
        """Perform snapshot cleanup.

        Perform snapshot cleanup before any other changes. If retyping
        to either async or metro then there should be no linked snapshots
        on the volume.
        :param array: the array serial number -- str
        :param device_id: device_id: the device id -- str
        :param was_rep_enabled: flag -- bool
        :param is_rep_enabled: flag -- bool
        :param backend_ids_differ: flag -- bool
        :param extra_specs: extra specs -- dict
        :param target_extra_specs: target extra specs -- dict
        """
        if (not was_rep_enabled and is_rep_enabled) or backend_ids_differ:
            target_rep_mode = target_extra_specs.get(utils.REP_MODE)
            target_is_async = target_rep_mode == utils.REP_ASYNC
            target_is_metro = target_rep_mode == utils.REP_METRO
            if target_is_async or target_is_metro:
                self._cleanup_device_snapvx(array, device_id, extra_specs)
                snapshots = self.rest.get_volume_snapshot_list(
                    array, device_id)
                __, snapvx_target_details = self.rest.find_snap_vx_sessions(
                    array, device_id, tgt_only=True)

                linked_snapshots = list()
                for snapshot in snapshots:
                    linked_devices = snapshot.get('linkedDevices')
                    if linked_devices:
                        snapshot_name = snapshot.get('snapshotName')
                        linked_snapshots.append(snapshot_name)
                if linked_snapshots:
                    snapshot_names = ', '.join(linked_snapshots)
                    raise exception.VolumeBackendAPIException(_(
                        'Unable to complete retype as volume has active'
                        'snapvx links. Cannot retype to Asynchronous or '
                        'Metro modes while the volume has active links. '
                        'Please wait until these snapvx operations have '
                        'completed and try again. Snapshots: '
                        '%s') % snapshot_names)
                if snapvx_target_details:
                    source_vol_id = snapvx_target_details.get('source_vol_id')
                    snap_name = snapvx_target_details.get('snap_name')
                    raise exception.VolumeBackendAPIException(_(
                        'Unable to complete retype as volume is a snapvx '
                        'target. Cannot retype to Asynchronous or Metro '
                        'modes in this state. Please wait until these snapvx '
                        'operations complete and try again. Volume %s is '
                        'currently a target of snapshot %s with source device '
                        '%s') % (device_id, snap_name, source_vol_id))

    def _cleanup_on_migrate_failure(
            self, rdf_pair_broken, rdf_pair_created, vol_retyped,
            remote_retyped, extra_specs, target_extra_specs, volume,
            volume_name, device_id, source_sg):
        """Attempt rollback to previous volume state before migrate exception.

        :param rdf_pair_broken: was the rdf pair broken during migration
        :param rdf_pair_created: was a new rdf pair created during migration
        :param vol_retyped: was the local volume retyped during migration
        :param remote_retyped: was the remote volume retyped during migration
        :param extra_specs: extra specs
        :param target_extra_specs: target extra specs
        :param volume: volume
        :param volume_name: volume name
        :param device_id: local device id
        :param source_sg: local device pre-migrate storage group name
        """
        array = extra_specs[utils.ARRAY]
        srp = extra_specs[utils.SRP]
        slo = extra_specs[utils.SLO]
        workload = extra_specs.get(utils.WORKLOAD, 'NONE')
        LOG.debug('Volume migrate cleanup - starting revert attempt.')
        if remote_retyped:
            LOG.debug('Volume migrate cleanup - Attempt to revert remote '
                      'volume retype.')
            rep_mode = extra_specs[utils.REP_MODE]
            is_rep_enabled = self.utils.is_replication_enabled(extra_specs)
            self._retype_remote_volume(
                array, volume, device_id, volume_name,
                rep_mode, is_rep_enabled, extra_specs)
            LOG.debug('Volume migrate cleanup - Revert remote retype '
                      'volume successful.')

        if rdf_pair_created:
            LOG.debug('Volume migrate cleanup - Attempt to revert rdf '
                      'pair creation.')
            rep_extra_specs, resume_rdf = (
                self.break_rdf_device_pair_session(
                    array, device_id, volume_name, extra_specs, volume))
            if resume_rdf:
                self.rest.srdf_resume_replication(
                    array, rep_extra_specs['mgmt_sg_name'],
                    rep_extra_specs['rdf_group_no'], rep_extra_specs)
            LOG.debug('Volume migrate cleanup - Revert rdf pair '
                      'creation successful.')

        if vol_retyped:
            LOG.debug('Volume migrate cleanup - Attempt to revert local '
                      'volume retype.')
            self._retype_volume(
                array, srp, device_id, volume, volume_name,
                target_extra_specs, slo, workload, extra_specs)
            LOG.debug('Volume migrate cleanup - Revert local volume '
                      'retype successful.')

        if rdf_pair_broken:
            LOG.debug('Volume migrate cleanup - Attempt to revert to '
                      'original rdf pair.')
            (rep_status, __, __, rep_extra_specs, resume_rdf) = (
                self.configure_volume_replication(
                    array, volume, device_id, extra_specs))
            if rep_status == 'first_vol_in_rdf_group':
                volume_name = self.utils.get_volume_element_name(volume.id)
                __, __, __ = (
                    self._post_retype_srdf_protect_storage_group(
                        array, source_sg, device_id, volume_name,
                        rep_extra_specs, volume))
            if resume_rdf:
                self.rest.srdf_resume_replication(
                    array, rep_extra_specs['mgmt_sg_name'],
                    rep_extra_specs['rdf_group_no'], rep_extra_specs)
            LOG.debug('Volume migrate cleanup - Revert to original rdf '
                      'pair successful.')
        LOG.debug('Volume migrate cleanup - Reverted volume to previous '
                  'state post retype exception.')

    def _retype_volume(
            self, array, srp, device_id, volume, volume_name, extra_specs,
            target_slo, target_workload, target_extra_specs, remote=False):
        """Retype a volume from one volume type to another.

        The target storage group ID is returned so the next phase in the
        calling function can SRDF protect it if required.

        :param array: the array serial number
        :param srp: the storage resource pool name
        :param device_id: the device ID to be retyped
        :param volume: the volume object
        :param volume_name: the volume name
        :param extra_specs: source extra specs
        :param target_slo: target service level id
        :param target_workload: target workload id
        :param target_extra_specs: target extra specs
        :param remote: if the volume being retyped is on a remote replication
                       target
        :returns: retype success, target storage group -- bool, str
        """
        is_re, rep_mode, mgmt_sg_name = False, None, None
        parent_sg = None
        if self.utils.is_replication_enabled(target_extra_specs):
            is_re, rep_mode = True, target_extra_specs['rep_mode']
            mgmt_sg_name = self.utils.get_rdf_management_group_name(
                target_extra_specs[utils.REP_CONFIG])
        if self.promotion and self.utils.is_replication_enabled(extra_specs):
            # Need to check this when performing promotion while R1 is offline
            # as RDF cleanup is not performed. Target is not RDF enabled
            # in that scenario.
            mgmt_sg_name = self.utils.get_rdf_management_group_name(
                extra_specs[utils.REP_CONFIG])

        device_info = self.rest.get_volume(array, device_id)

        target_extra_specs[utils.PORTGROUPNAME] = (
            extra_specs.get(utils.PORTGROUPNAME, None))
        disable_compression = self.utils.is_compression_disabled(
            target_extra_specs)
        source_sg_list = device_info['storageGroupId']
        if mgmt_sg_name in source_sg_list:
            source_sg_list.remove(mgmt_sg_name)
        source_sg_name = source_sg_list[0]

        # Flags for exception handling
        (created_child_sg, add_sg_to_parent, got_default_sg, moved_between_sgs,
         target_sg_name) = (False, False, False, False, False)
        try:
            # If volume is attached set up the parent/child SGs if not already
            # present on array
            if volume.attach_status == 'attached' and not remote:
                attached_host = self.utils.get_volume_attached_hostname(
                    volume)
                if not attached_host:
                    LOG.error(
                        "There was an issue retrieving attached host from "
                        "volume %(volume_name)s, aborting storage-assisted "
                        "migration.", {'volume_name': device_id})
                    return False, None

                port_group_label = self.utils.get_port_name_label(
                    target_extra_specs[utils.PORTGROUPNAME],
                    self.powermax_port_group_name_template)

                target_sg_name, __, __ = self.utils.get_child_sg_name(
                    attached_host, target_extra_specs, port_group_label)
                target_sg = self.rest.get_storage_group(array, target_sg_name)

                if not target_sg:
                    self.provision.create_storage_group(
                        array, target_sg_name, srp, target_slo,
                        target_workload, target_extra_specs,
                        disable_compression)
                    source_sg = self.rest.get_storage_group(
                        array, source_sg_name)
                    parent_sg = source_sg.get('parent_storage_group', None)
                    created_child_sg = True

                    if parent_sg:
                        parent_sg = parent_sg[0]
                        self.masking.add_child_sg_to_parent_sg(
                            array, target_sg_name, parent_sg,
                            target_extra_specs)
                        add_sg_to_parent = True

            # Else volume is not attached or is remote volume, use default SGs
            else:
                target_sg_name = (
                    self.masking.get_or_create_default_storage_group(
                        array, srp, target_slo, target_workload, extra_specs,
                        disable_compression, is_re, rep_mode))
                got_default_sg = True

            # Move the volume from the source to target storage group
            self.masking.move_volume_between_storage_groups(
                array, device_id, source_sg_name, target_sg_name, extra_specs,
                force=True, parent_sg=parent_sg)
            moved_between_sgs = True

            # Check if volume should be member of GVG
            self.masking.return_volume_to_volume_group(
                array, volume, device_id, volume_name, extra_specs)

            # Check the move was successful
            success = self.rest.is_volume_in_storagegroup(
                array, device_id, target_sg_name)
            if not success:
                LOG.error(
                    "Volume: %(volume_name)s has not been "
                    "added to target storage group %(storageGroup)s.",
                    {'volume_name': device_id,
                     'storageGroup': target_sg_name})
                return False, None
            else:
                LOG.info("Move successful: %(success)s", {'success': success})
                return success, target_sg_name
        except Exception as e:
            try:
                self._cleanup_on_retype_volume_failure(
                    created_child_sg, add_sg_to_parent, got_default_sg,
                    moved_between_sgs, array, source_sg_name, parent_sg,
                    target_sg_name, extra_specs, device_id, volume,
                    volume_name)
            except Exception:
                # Don't care what this is, just catch it to prevent exception
                # occurred while handling another exception type stack trace.
                LOG.debug(
                    'Volume retype cleanup - Could not revert volume to '
                    'previous state post volume retype exception.')
            finally:
                raise e

    def _cleanup_on_retype_volume_failure(
            self, created_child_sg, add_sg_to_parent, got_default_sg,
            moved_between_sgs, array, source_sg, parent_sg, target_sg_name,
            extra_specs, device_id, volume, volume_name):
        """Attempt to rollback to previous volume state on retype exception.

        :param created_child_sg: was a child sg created during retype
        :param add_sg_to_parent: was a child sg added to parent during retype
        :param got_default_sg: was a default sg possibly created during retype
        :param moved_between_sgs: was the volume moved between storage groups
        :param array: array
        :param source_sg: volumes originating storage group name
        :param parent_sg: parent storage group name
        :param target_sg_name: storage group volume was to be moved to
        :param extra_specs: extra specs
        :param device_id: device id
        :param volume: volume
        :param volume_name: volume name
        """
        if moved_between_sgs:
            LOG.debug('Volume retype cleanup - Attempt to revert move between '
                      'storage groups.')
            storage_groups = self.rest.get_storage_group_list(array)
            if source_sg not in storage_groups:
                disable_compression = self.utils.is_compression_disabled(
                    extra_specs)
                self.rest.create_storage_group(
                    array, source_sg, extra_specs['srp'], extra_specs['slo'],
                    extra_specs['workload'], extra_specs, disable_compression)
                if parent_sg:
                    self.masking.add_child_sg_to_parent_sg(
                        array, source_sg, parent_sg, extra_specs)
            self.masking.move_volume_between_storage_groups(
                array, device_id, target_sg_name, source_sg, extra_specs,
                force=True, parent_sg=parent_sg)
            self.masking.return_volume_to_volume_group(
                array, volume, device_id, volume_name, extra_specs)
            LOG.debug('Volume retype cleanup - Revert move between storage '
                      'groups successful.')
        elif got_default_sg:
            vols = self.rest.get_volumes_in_storage_group(
                array, target_sg_name)
            if len(vols) == 0:
                LOG.debug('Volume retype cleanup - Attempt to delete empty '
                          'target sg.')
                self.rest.delete_storage_group(array, target_sg_name)
                LOG.debug('Volume retype cleanup - Delete target sg '
                          'successful')
        elif created_child_sg:
            if add_sg_to_parent:
                LOG.debug('Volume retype cleanup - Attempt to revert add '
                          'child sg to parent')
                self.rest.remove_child_sg_from_parent_sg(
                    array, target_sg_name, parent_sg, extra_specs)
                LOG.debug('Volume retype cleanup - Revert add child sg to '
                          'parent successful.')
            LOG.debug('Volume retype cleanup - Attempt to delete empty '
                      'target sg.')
            self.rest.delete_storage_group(array, target_sg_name)
            LOG.debug('Volume retype cleanup - Delete target sg '
                      'successful')

    def remove_stale_data(self, model_update):
        """Remove stale RDF data

        :param model_update: the model
        :returns: model_update -- dict
        """

        new_metadata = model_update.get('metadata')

        if isinstance(new_metadata, dict):
            keys = ['R2-DeviceID', 'R2-ArrayID', 'R2-ArrayModel',
                    'ReplicationMode', 'RDFG-Label', 'R1-RDFG', 'R2-RDFG',
                    'BackendID']
            for k in keys:
                new_metadata.pop(k, None)
        return model_update

    def _post_retype_srdf_protect_storage_group(
            self, array, local_sg_name, device_id, volume_name,
            rep_extra_specs, volume):
        """SRDF protect SG if first volume in SG after retype operation.

        :param array: the array serial number
        :param local_sg_name: the local storage group name
        :param device_id: the local device ID
        :param volume_name: the volume name
        :param rep_extra_specs: replication info dictionary
        :param volume: the volume being used
        :returns: replication enables status, device pair info,
                  remote device id -- str, dict, str
        """
        rep_mode = rep_extra_specs['rep_mode']
        remote_array = rep_extra_specs['array']
        rdf_group_no = rep_extra_specs['rdf_group_no']
        service_level = rep_extra_specs['slo']

        remote_sg_name = self.utils.derive_default_sg_from_extra_specs(
            rep_extra_specs, rep_mode)
        # Flags for exception handling
        rdf_pair_created = False
        try:
            self.rest.srdf_protect_storage_group(
                array, remote_array, rdf_group_no, rep_mode, local_sg_name,
                service_level, rep_extra_specs, target_sg=remote_sg_name)
            rdf_pair_created = True

            pair_info = self.rest.get_rdf_pair_volume(
                array, rdf_group_no, device_id)
            r2_device_id = pair_info['remoteVolumeName']
            self.rest.rename_volume(remote_array, r2_device_id, volume_name)

            if rep_mode in [utils.REP_ASYNC, utils.REP_METRO]:
                self._add_volume_to_rdf_management_group(
                    array, device_id, volume_name, remote_array,
                    r2_device_id, rep_extra_specs)

            return REPLICATION_ENABLED, pair_info, r2_device_id
        except Exception as e:
            try:
                if rdf_pair_created:
                    LOG.debug('Volume retype srdf protect cleanup - Attempt '
                              'to break new rdf pair.')
                    self.break_rdf_device_pair_session(
                        array, device_id, volume_name, rep_extra_specs, volume)
                    LOG.debug('Volume retype srdf protect cleanup - Break new '
                              'rdf pair successful.')
            except Exception:
                # Don't care what this is, just catch it to prevent exception
                # occurred while handling another exception type stack trace.
                LOG.debug(
                    'Retype SRDF protect cleanup - Unable to break new RDF '
                    'pair on volume post volume retype srdf protect '
                    'exception.')
            finally:
                raise e

    def _retype_remote_volume(self, array, volume, device_id,
                              volume_name, rep_mode, is_re, extra_specs):
        """Retype the remote volume.

        :param array: the array serial number
        :param volume: the volume object
        :param device_id: the device id
        :param volume_name: the volume name
        :param rep_mode: the replication mode
        :param is_re: replication enabled
        :param extra_specs: the target extra specs
        :returns: bool
        """
        success = True
        rep_config = extra_specs[utils.REP_CONFIG]
        rep_extra_specs = self._get_replication_extra_specs(
            extra_specs, rep_config)
        target_device = self.rest.get_rdf_pair_volume(
            array, rep_extra_specs['rdf_group_no'], device_id)
        target_device_id = target_device['remoteVolumeName']
        remote_array = rep_extra_specs['array']
        rep_compr_disabled = self.utils.is_compression_disabled(
            rep_extra_specs)

        remote_sg_name = self.masking.get_or_create_default_storage_group(
            remote_array, rep_extra_specs[utils.SRP],
            rep_extra_specs[utils.SLO], rep_extra_specs[utils.WORKLOAD],
            rep_extra_specs, rep_compr_disabled,
            is_re=is_re, rep_mode=rep_mode)

        found_storage_group_list = self.rest.get_storage_groups_from_volume(
            remote_array, target_device_id)
        move_rqd = True
        for found_storage_group_name in found_storage_group_list:
            # Check if remote volume is already in the correct sg
            if found_storage_group_name == remote_sg_name:
                move_rqd = False
                break
        if move_rqd:
            try:
                success, __ = self._retype_volume(
                    remote_array, rep_extra_specs[utils.SRP],
                    target_device_id, volume, volume_name, rep_extra_specs,
                    extra_specs[utils.SLO], extra_specs[utils.WORKLOAD],
                    extra_specs, remote=True)
            except Exception as e:
                try:
                    volumes = self.rest.get_volumes_in_storage_group(
                        remote_array, remote_sg_name)
                    if len(volumes) == 0:
                        LOG.debug('Volume retype remote cleanup - Attempt to '
                                  'delete target sg.')
                        self.rest.delete_storage_group(
                            remote_array, remote_sg_name)
                        LOG.debug('Volume retype remote cleanup - Delete '
                                  'target sg successful.')
                except Exception:
                    # Don't care what this is, just catch it to prevent
                    # exception occurred while handling another exception
                    # type messaging.
                    LOG.debug(
                        'Retype remote volume cleanup - Could not delete '
                        'target storage group on remote array post retype '
                        'remote volume exception.')
                finally:
                    raise e
        return success

    def _is_valid_for_storage_assisted_migration(
            self, device_id, host, source_array, source_srp, volume_name,
            do_change_compression, do_change_replication, source_slo,
            source_workload, is_tgt_rep):
        """Check if volume is suitable for storage assisted (pool) migration.

        :param device_id: the volume device id
        :param host: the host dict
        :param source_array: the volume's current array serial number
        :param source_srp: the volume's current pool name
        :param volume_name: the name of the volume to be migrated
        :param do_change_compression: do change compression
        :param do_change_replication: flag indicating replication change
        :param source_slo: slo setting for source volume type
        :param source_workload: workload setting for source volume type
        :param is_tgt_rep: is the target volume type replication enabled
        :returns: boolean -- True/False
        :returns: string -- targetSlo
        :returns: string -- targetWorkload
        """
        false_ret = (False, None, None)
        host_info = host['host']

        LOG.debug("Target host is : %(info)s.", {'info': host_info})
        try:
            info_detail = host_info.split('#')
            pool_details = info_detail[1].split('+')
            if len(pool_details) == 4:
                target_slo = pool_details[0]
                if pool_details[1].lower() == 'none':
                    target_workload = 'NONE'
                else:
                    target_workload = pool_details[1]
                target_srp = pool_details[2]
                target_array_serial = pool_details[3]
            elif len(pool_details) == 3:
                target_slo = pool_details[0]
                target_srp = pool_details[1]
                target_array_serial = pool_details[2]
                target_workload = 'NONE'
            else:
                raise IndexError
            if target_slo.lower() == 'none':
                target_slo = None
            if self.rest.is_next_gen_array(target_array_serial):
                target_workload = 'NONE'
        except IndexError:
            LOG.error("Error parsing array, pool, SLO and workload.")
            return false_ret

        if self.promotion:
            if do_change_compression:
                LOG.error(
                    "When retyping during array promotion, compression "
                    "changes should not occur during the retype operation. "
                    "Please ensure the same compression settings are defined "
                    "in the source and target volume types.")
                return false_ret

            if source_slo != target_slo:
                LOG.error(
                    "When retyping during array promotion, the SLO setting "
                    "for the source and target volume types should match. "
                    "Found %s SLO for the source volume type and %s SLO for "
                    "the target volume type.", source_slo, target_slo)
                return false_ret

            if source_workload != target_workload:
                LOG.error(
                    "When retyping during array promotion, the workload "
                    "setting for the source and target volume types should "
                    "match. Found %s workload for the source volume type "
                    "and %s workload for the target volume type.",
                    source_workload, target_workload)
                return false_ret

            if is_tgt_rep:
                LOG.error(
                    "When retyping during array promotion, the target volume "
                    "type should not have replication enabled. Please ensure "
                    "replication is disabled on the target volume type.")
                return false_ret

        if not self.promotion:
            if target_array_serial not in source_array:
                LOG.error("The source array: %s does not match the target "
                          "array: %s - skipping storage-assisted "
                          "migration.", source_array, target_array_serial)
                return false_ret

            if target_srp not in source_srp:
                LOG.error(
                    "Only SLO/workload migration within the same SRP Pool is "
                    "supported in this version. The source pool: %s does not "
                    "match the target array: %s. Skipping storage-assisted "
                    "migration.", source_srp, target_srp)
                return false_ret

        found_storage_group_list = self.rest.get_storage_groups_from_volume(
            source_array, device_id)
        if not found_storage_group_list:
            LOG.warning("Volume: %(volume_name)s does not currently "
                        "belong to any storage groups.",
                        {'volume_name': volume_name})

        else:
            for found_storage_group_name in found_storage_group_list:
                emc_fast_setting = (
                    self.provision.
                    get_slo_workload_settings_from_storage_group(
                        source_array, found_storage_group_name))
                target_combination = ("%(targetSlo)s+%(targetWorkload)s"
                                      % {'targetSlo': target_slo,
                                         'targetWorkload': target_workload})
                if target_combination == emc_fast_setting:
                    # Check if migration is to change compression
                    # or replication types
                    action_rqd = (True if do_change_compression
                                  or do_change_replication else False)
                    if not action_rqd:
                        LOG.warning(
                            "No action required. Volume: %(volume_name)s is "
                            "already part of slo/workload combination: "
                            "%(targetCombination)s.",
                            {'volume_name': volume_name,
                             'targetCombination': target_combination})
                        return false_ret

        return True, target_slo, target_workload

    def configure_volume_replication(self, array, volume, device_id,
                                     extra_specs):
        """Configure volume replication for a source device.

        :param array: the array serial number
        :param volume: the volume object
        :param device_id: the device id
        :param extra_specs: volume extra specifications
        :returns: replication status, device pair info, replication info,
                  resume rdf -- str, dict, dict, bool
        """
        # Set session attributes
        LOG.debug('Starting replication setup for volume %(vol)s',
                  {'vol': volume.name})
        resume_rdf, mgmt_sg_name = False, None
        disable_compression = self.utils.is_compression_disabled(
            extra_specs)
        rep_config = extra_specs[utils.REP_CONFIG]
        rdf_group_no, remote_array = self.get_rdf_details(
            array, rep_config)
        rep_extra_specs = self._get_replication_extra_specs(
            extra_specs, rep_config)
        rep_mode = rep_extra_specs['rep_mode']
        rep_extra_specs['mgmt_sg_name'] = None
        group_details = self.rest.get_rdf_group(array, rdf_group_no)

        if group_details['numDevices'] == 0:
            rep_info = {
                'remote_array': remote_array, 'rdf_group_no': rdf_group_no,
                'rep_mode': rep_mode, 'slo': rep_extra_specs['slo'],
                'extra_specs': rep_extra_specs, 'target_device_id': None}
            return ('first_vol_in_rdf_group', None, rep_info,
                    rep_extra_specs, False)

        # Flags for exception handling
        (rdf_pair_created, remote_sg_get, add_to_mgmt_sg,
         r2_device_id, tgt_sg_name) = (False, False, False, False, False)
        try:
            if group_details['numDevices'] > 0 and (
                    rep_mode in [utils.REP_ASYNC, utils.REP_METRO]):
                mgmt_sg_name = self.utils.get_rdf_management_group_name(
                    rep_config)
                self.rest.srdf_suspend_replication(
                    array, mgmt_sg_name, rdf_group_no, rep_extra_specs)
                rep_extra_specs['mgmt_sg_name'] = mgmt_sg_name
                resume_rdf = True

            pair_info = self.rest.srdf_create_device_pair(
                array, rdf_group_no, rep_mode, device_id, rep_extra_specs,
                self.next_gen)
            rdf_pair_created = True

            r2_device_id = pair_info['tgt_device']
            device_uuid = self.utils.get_volume_element_name(volume.id)
            self.rest.rename_volume(remote_array, r2_device_id, device_uuid)

            tgt_sg_name = self.masking.get_or_create_default_storage_group(
                remote_array, rep_extra_specs['srp'], rep_extra_specs['slo'],
                rep_extra_specs['workload'], rep_extra_specs,
                disable_compression, is_re=True, rep_mode=rep_mode)
            remote_sg_get = True

            self.rest.add_vol_to_sg(remote_array, tgt_sg_name, r2_device_id,
                                    rep_extra_specs, force=True)

            if rep_mode in [utils.REP_ASYNC, utils.REP_METRO]:
                self._add_volume_to_rdf_management_group(
                    array, device_id, device_uuid, remote_array, r2_device_id,
                    extra_specs)
                add_to_mgmt_sg = True

            rep_status = REPLICATION_ENABLED
            target_name = self.utils.get_volume_element_name(volume.id)
            rep_info_dict = self.volume_metadata.gather_replication_info(
                volume.id, 'replication', False,
                rdf_group_no=rdf_group_no, target_name=target_name,
                remote_array=remote_array, target_device_id=r2_device_id,
                replication_status=rep_status, rep_mode=rep_mode,
                rdf_group_label=rep_config['rdf_group_label'],
                target_array_model=rep_extra_specs['target_array_model'],
                mgmt_sg_name=rep_extra_specs['mgmt_sg_name'])

            return (rep_status, pair_info, rep_info_dict, rep_extra_specs,
                    resume_rdf)
        except Exception as e:
            try:
                self._cleanup_on_configure_volume_replication_failure(
                    resume_rdf, rdf_pair_created, remote_sg_get,
                    add_to_mgmt_sg, device_id, r2_device_id, mgmt_sg_name,
                    array, remote_array, rdf_group_no, extra_specs,
                    rep_extra_specs, volume, tgt_sg_name)
            except Exception:
                # Don't care what this is, just catch it to prevent exception
                # occurred while handling another exception type stack trace.
                LOG.debug(
                    'Configure volume replication cleanup - Could not revert '
                    'volume to non-rdf state post configure volume '
                    'replication exception.')
            raise e

    def _cleanup_on_configure_volume_replication_failure(
            self, resume_rdf, rdf_pair_created, remote_sg_get,
            add_to_mgmt_sg, r1_device_id, r2_device_id,
            mgmt_sg_name, array, remote_array, rdf_group_no, extra_specs,
            rep_extra_specs, volume, tgt_sg_name):
        """Attempt rollback to previous volume state on setup rep exception.

        :param resume_rdf: does the rdfg need to be resumed
        :param rdf_pair_created: was an rdf pair created
        :param remote_sg_get: was a remote storage group possibly created
        :param add_to_mgmt_sg: was the volume added to a management group
        :param r1_device_id: local device id
        :param r2_device_id: remote device id
        :param mgmt_sg_name: rdfg management storage group name
        :param array: array
        :param remote_array: remote array
        :param rdf_group_no: rdf group number
        :param extra_specs: extra specs
        :param rep_extra_specs: rep extra specs
        :param volume: volume
        :param tgt_sg_name: remote replication storage group name
        """
        if resume_rdf and not rdf_pair_created:
            LOG.debug('Configure volume replication cleanup - Attempt to '
                      'resume replication.')
            self.rest.srdf_resume_replication(
                array, mgmt_sg_name, rdf_group_no, rep_extra_specs)
            LOG.debug('Configure volume replication cleanup - Resume '
                      'replication successful.')
        elif rdf_pair_created:
            volume_name = self.utils.get_volume_element_name(volume.id)
            LOG.debug('Configure volume replication cleanup - Attempt to '
                      'break new rdf pair.')
            rep_extra_specs, resume_rdf = (
                self.break_rdf_device_pair_session(
                    array, r1_device_id, volume_name, extra_specs, volume))
            if resume_rdf:
                self.rest.srdf_resume_replication(
                    array, rep_extra_specs['mgmt_sg_name'],
                    rep_extra_specs['rdf_group_no'], rep_extra_specs)
            LOG.debug('Configure volume replication cleanup - Break new rdf '
                      'pair successful.')

            if add_to_mgmt_sg:
                LOG.debug('Configure volume replication cleanup - Attempt to '
                          'remove r1 device from mgmt sg.')
                self.masking.remove_vol_from_storage_group(
                    array, r1_device_id, mgmt_sg_name, '', extra_specs)
                LOG.debug('Configure volume replication cleanup - Remove r1 '
                          'device from mgmt sg successful.')
                LOG.debug('Configure volume replication cleanup - Attempt to '
                          'remove r2 device from mgmt sg.')
                self.masking.remove_vol_from_storage_group(
                    remote_array, r2_device_id, mgmt_sg_name, '',
                    rep_extra_specs)
                LOG.debug('Configure volume replication cleanup - Remove r2 '
                          'device from mgmt sg successful.')

            if remote_sg_get:
                volumes = self.rest.get_volumes_in_storage_group(
                    remote_array, tgt_sg_name)
                if len(volumes) == 0:
                    LOG.debug('Configure volume replication cleanup - Attempt '
                              'to delete empty target sg.')
                    self.rest.delete_storage_group(remote_array, tgt_sg_name)
                    LOG.debug('Configure volume replication cleanup - Delete '
                              'empty target sg successful.')
                elif r2_device_id in volumes:
                    LOG.debug('Configure volume replication cleanup - Attempt '
                              'to remove r2 device and delete sg.')
                    self.masking.remove_vol_from_storage_group(
                        remote_array, r2_device_id, tgt_sg_name, '',
                        rep_extra_specs)
                    LOG.debug('Configure volume replication cleanup - Remove '
                              'r2 device and delete sg successful.')

    def _add_volume_to_rdf_management_group(
            self, array, device_id, volume_name, remote_array,
            target_device_id, extra_specs):
        """Add a volume to its rdf management group.

        :param array: the array serial number
        :param device_id: the device id
        :param volume_name: the volume name
        :param remote_array: the remote array
        :param target_device_id: the target device id
        :param extra_specs: the extra specifications
        :raises: VolumeBackendAPIException
        """
        grp_name = self.utils.get_rdf_management_group_name(
            extra_specs[utils.REP_CONFIG])
        try:
            self.provision.get_or_create_group(array, grp_name, extra_specs)
            self.masking.add_volume_to_storage_group(
                array, device_id, grp_name, volume_name, extra_specs,
                force=True)
            # Add remote volume
            self.provision.get_or_create_group(
                remote_array, grp_name, extra_specs)
            self.masking.add_volume_to_storage_group(
                remote_array, target_device_id, grp_name, volume_name,
                extra_specs, force=True)
        except Exception as e:
            exception_message = (
                _('Exception occurred adding volume %(vol)s to its '
                  'rdf management group - the exception received was: %(e)s')
                % {'vol': volume_name, 'e': six.text_type(e)})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

    def break_rdf_device_pair_session(self, array, device_id, volume_name,
                                      extra_specs, volume):
        """Delete RDF device pair deleting R2 volume but leaving R1 in place.

        :param array: the array serial number
        :param device_id: the device id
        :param volume_name: the volume name
        :param extra_specs: the volume extra specifications
        :param volume: the volume being used
        :returns: replication extra specs, resume rdf -- dict, bool
        """
        LOG.debug('Starting replication cleanup for RDF pair source device: '
                  '%(d_id)s.', {'d_id': device_id})

        # Set session attributes
        resume_rdf, mgmt_sg_name = True, None

        rep_config = extra_specs[utils.REP_CONFIG]
        rep_extra_specs = self._get_replication_extra_specs(
            extra_specs, rep_config)

        remote_array = rep_extra_specs['array']
        rdfg_no = rep_extra_specs['rdf_group_no']
        remote_device = self.rest.get_rdf_pair_volume(
            array, rdfg_no, device_id)
        remote_device_id = remote_device['remoteVolumeName']

        extra_specs[utils.FORCE_VOL_EDIT] = True
        rep_extra_specs[utils.FORCE_VOL_EDIT] = True

        # Get the names of the SGs associated with the volume on the R2 array
        # before any operations are carried out - this will be used later for
        # remove vol operations
        r1_sg_names = self.rest.get_storage_groups_from_volume(
            array, device_id)
        r2_sg_names = self.rest.get_storage_groups_from_volume(
            remote_array, remote_device_id)

        if rep_config['mode'] in [utils.REP_ASYNC, utils.REP_METRO]:
            mgmt_sg_name = self.utils.get_rdf_management_group_name(rep_config)
            sg_name = mgmt_sg_name
            rdf_group_state = self.rest.get_storage_group_rdf_group_state(
                array, sg_name, rdfg_no)
            if len(rdf_group_state) > 1 or (
                    rdf_group_state[0] not in utils.RDF_SYNCED_STATES):
                self.rest.wait_for_rdf_group_sync(
                    array, sg_name, rdfg_no, rep_extra_specs)
        else:
            sg_name = r1_sg_names[0]
            rdf_pair = self.rest.get_rdf_pair_volume(
                array, rdfg_no, device_id)
            rdf_pair_state = rdf_pair[utils.RDF_PAIR_STATE]
            if rdf_pair_state.lower() not in utils.RDF_SYNCED_STATES:
                self.rest.wait_for_rdf_pair_sync(
                    array, rdfg_no, device_id, rep_extra_specs)

        # Flags for exception handling
        rdfg_suspended, pair_deleted, r2_sg_remove = False, False, False
        try:
            self.rest.srdf_suspend_replication(
                array, sg_name, rdfg_no, rep_extra_specs)
            rdfg_suspended = True
            self.rest.srdf_delete_device_pair(array, rdfg_no, device_id)
            pair_deleted = True

            # Remove the volume from the R1 RDFG mgmt SG (R1)
            if rep_config['mode'] in [utils.REP_ASYNC, utils.REP_METRO]:
                self.masking.remove_volume_from_sg(
                    array, device_id, volume_name, mgmt_sg_name, extra_specs)

            # Remove volume from R2 replication SGs
            for r2_sg_name in r2_sg_names:
                self.masking.remove_volume_from_sg(
                    remote_array, remote_device_id, volume_name, r2_sg_name,
                    rep_extra_specs)
            r2_sg_remove = True

            if mgmt_sg_name:
                if not self.rest.get_volumes_in_storage_group(
                        array, mgmt_sg_name):
                    resume_rdf = False
            else:
                if not self.rest.get_volumes_in_storage_group(array, sg_name):
                    resume_rdf = False

            if resume_rdf:
                rep_extra_specs['mgmt_sg_name'] = sg_name

            self._delete_from_srp(remote_array, remote_device_id, volume_name,
                                  extra_specs)

            return rep_extra_specs, resume_rdf
        except Exception as e:
            try:
                self._cleanup_on_break_rdf_device_pair_session_failure(
                    rdfg_suspended, pair_deleted, r2_sg_remove, array,
                    mgmt_sg_name, rdfg_no, extra_specs, r2_sg_names,
                    device_id, remote_array, remote_device_id, volume,
                    volume_name, rep_extra_specs)
            except Exception:
                # Don't care what this is, just catch it to prevent exception
                # occurred while handling another exception type stack trace.
                LOG.debug(
                    'Break rdf pair cleanup - Could not revert '
                    'volume to previous rdf enabled state post break rdf '
                    'device pair exception replication exception.')
            finally:
                raise e

    def _cleanup_on_break_rdf_device_pair_session_failure(
            self, rdfg_suspended, pair_deleted, r2_sg_remove, array,
            management_sg, rdf_group_no, extra_specs, r2_sg_names, device_id,
            remote_array, remote_device_id, volume, volume_name,
            rep_extra_specs):
        """Attempt rollback to previous volume state on remove rep exception.

        :param rdfg_suspended: was the rdf group suspended
        :param pair_deleted: was the rdf pair deleted
        :param r2_sg_remove: was the remote volume removed from its sg
        :param array: array
        :param management_sg: rdf management storage group name
        :param rdf_group_no: rdf group number
        :param extra_specs: extra specs
        :param r2_sg_names: remote volume storage group names
        :param device_id: device id
        :param remote_array: remote array sid
        :param remote_device_id: remote device id
        :param volume: volume
        :param volume_name: volume name
        :param rep_extra_specs: rep extra specs
        """
        if rdfg_suspended and not pair_deleted:
            LOG.debug('Break RDF pair cleanup - Attempt to resume RDFG.')
            self.rest.srdf_resume_replication(
                array, management_sg, rdf_group_no, extra_specs)
            LOG.debug('Break RDF pair cleanup - Resume RDFG successful.')
        elif pair_deleted:
            LOG.debug('Break RDF pair cleanup - Attempt to cleanup remote '
                      'volume storage groups.')
            # Need to cleanup the remote SG in case of first RDFG vol scenario
            if not r2_sg_remove:
                for r2_sg_name in r2_sg_names:
                    self.masking.remove_volume_from_sg(
                        remote_array, remote_device_id, volume_name,
                        r2_sg_name, rep_extra_specs)
            LOG.debug('Break RDF pair cleanup - Cleanup remote volume storage '
                      'groups successful.')

            LOG.debug('Break RDF pair cleanup - Attempt to delete remote '
                      'volume.')
            self._delete_from_srp(remote_array, remote_device_id, volume_name,
                                  extra_specs)
            LOG.debug('Break RDF pair cleanup - Delete remote volume '
                      'successful.')

            LOG.debug('Break RDF pair cleanup - Attempt to revert to '
                      'original rdf pair.')
            (rep_status, __, __, rep_extra_specs, resume_rdf) = (
                self.configure_volume_replication(
                    array, volume, device_id, extra_specs))
            if rep_status == 'first_vol_in_rdf_group':
                volume_name = self.utils.get_volume_element_name(volume.id)
                self._protect_storage_group(
                    array, device_id, volume, volume_name, rep_extra_specs)
            if resume_rdf:
                self.rest.srdf_resume_replication(
                    array, rep_extra_specs['mgmt_sg_name'],
                    rep_extra_specs['rdf_group_no'], rep_extra_specs)
            LOG.debug('Break RDF pair cleanup - Revert to original rdf '
                      'pair successful.')

    def break_rdf_device_pair_session_promotion(
            self, array, device_id, volume_name, extra_specs):
        """Delete RDF device pair deleting R2 volume but leaving R1 in place.

        :param array: the array serial number
        :param device_id: the device id
        :param volume_name: the volume name
        :param extra_specs: the volume extra specifications
        """
        LOG.debug('Starting promotion replication cleanup for RDF pair '
                  'source device: %(d_id)s.', {'d_id': device_id})

        mgmt_sg_name = None
        rep_config = extra_specs[utils.REP_CONFIG]
        rdfg_no = extra_specs['rdf_group_no']
        extra_specs[utils.FORCE_VOL_EDIT] = True
        if rep_config['mode'] in [utils.REP_ASYNC, utils.REP_METRO]:
            mgmt_sg_name = self.utils.get_rdf_management_group_name(
                rep_config)

        if rep_config['mode'] == utils.REP_METRO:
            group_states = self.rest.get_storage_group_rdf_group_state(
                array, mgmt_sg_name, rdfg_no)
            group_states = set([x.lower() for x in group_states])
            metro_active_states = {
                utils.RDF_ACTIVE, utils.RDF_ACTIVEACTIVE, utils.RDF_ACTIVEBIAS}
            active_state_found = (
                bool(group_states.intersection(metro_active_states)))
            if active_state_found:
                LOG.debug('Found Metro RDF in active state during promotion, '
                          'attempting to suspend.')
                try:
                    self.rest.srdf_suspend_replication(
                        array, mgmt_sg_name, rdfg_no, extra_specs)
                except exception.VolumeBackendAPIException:
                    LOG.error(
                        'Found Metro rdf pair in active state during '
                        'promotion. Attempt to suspend this group using '
                        'storage group %s failed. Please move the rdf pairs '
                        'in this storage group to a non-active state and '
                        'retry the retype operation.', mgmt_sg_name)
                    raise
        self.rest.srdf_delete_device_pair(array, rdfg_no, device_id)
        # Remove the volume from the R1 RDFG mgmt SG (R1)
        if rep_config['mode'] in [utils.REP_ASYNC, utils.REP_METRO]:
            self.masking.remove_volume_from_sg(
                array, device_id, volume_name, mgmt_sg_name, extra_specs)

    @coordination.synchronized('emc-{rdf_group}-rdf')
    def _cleanup_remote_target(
            self, array, volume, remote_array, device_id, target_device,
            rdf_group, volume_name, rep_extra_specs):
        """Clean-up remote replication target after exception or on deletion.

        :param array: the array serial number
        :param volume: the volume object
        :param remote_array: the remote array serial number
        :param device_id: the source device id
        :param target_device: the target device id
        :param rdf_group: the RDF group
        :param volume_name: the volume name
        :param rep_extra_specs: replication extra specifications
        """
        are_vols_paired, __, pair_state = (
            self.rest.are_vols_rdf_paired(
                array, remote_array, device_id, target_device))
        if are_vols_paired:
            async_grp = None
            rep_mode = rep_extra_specs['rep_mode']
            if rep_mode in [utils.REP_ASYNC, utils.REP_METRO]:
                async_grp = self.utils.get_rdf_management_group_name(
                    rep_extra_specs[utils.REP_CONFIG])

            sg_name = self.rest.get_storage_groups_from_volume(
                array, device_id)
            self.provision.break_rdf_relationship(
                array, device_id, sg_name, rdf_group,
                rep_extra_specs, pair_state)
            self.masking.remove_and_reset_members(
                remote_array, volume, target_device, volume_name,
                rep_extra_specs, sg_name)
            if async_grp:
                self.masking.remove_and_reset_members(
                    remote_array, volume, target_device, volume_name,
                    rep_extra_specs, async_grp)

            rdfg_details = self.rest.get_rdf_group(array, rdf_group)
            if rdfg_details and int(rdfg_details.get('numDevices', 0)):
                self.rest.srdf_resume_replication(
                    array, sg_name, rdf_group, rep_extra_specs)
        self._delete_from_srp(
            remote_array, target_device, volume_name, rep_extra_specs)

    def _cleanup_replication_source(
            self, array, volume, volume_name, volume_dict, extra_specs):
        """Cleanup a remote replication source volume on failure.

        If replication setup fails at any stage on a new volume create,
        we must clean-up the source instance as the cinder database won't
        be updated with the provider_location. This means the volume cannot
        be properly deleted from the array by cinder.
        :param array: the array serial number
        :param volume: the volume object
        :param volume_name: the name of the volume
        :param volume_dict: the source volume dictionary
        :param extra_specs: the extra specifications
        """
        LOG.warning(
            "Replication failed. Cleaning up the source volume. "
            "Volume name: %(sourceName)s ",
            {'sourceName': volume_name})
        device_id = volume_dict['device_id']
        # Check if volume is snap target (e.g. if clone volume)
        self._cleanup_device_snapvx(array, device_id, extra_specs)
        # Remove from any storage groups and cleanup replication
        self._remove_vol_and_cleanup_replication(
            array, device_id, volume_name, extra_specs, volume)
        self._delete_from_srp(
            array, device_id, volume_name, extra_specs)

    def get_rdf_details(self, array, rep_config):
        """Retrieves an SRDF group instance.

        :param array: the array serial number
        :param rep_config: rep config to get details of
        :returns: rdf_group_no, remote_array
        """
        if not self.rep_configs:
            exception_message = (_("Replication is not configured on "
                                   "backend: %(backend)s.") %
                                 {'backend': self.configuration.safe_get(
                                     'volume_backend_name')})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        remote_array = rep_config['array']
        rdf_group_label = rep_config['rdf_group_label']
        LOG.info("Replication group: %(RDFGroup)s.",
                 {'RDFGroup': rdf_group_label})
        rdf_group_no = self.rest.get_rdf_group_number(array, rdf_group_label)
        if rdf_group_no is None:
            exception_message = (_("Cannot find replication group: "
                                   "%(RDFGroup)s. Please check the name "
                                   "and the array") %
                                 {'RDFGroup': rdf_group_label})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        LOG.info("Found RDF group number: %(RDFGroup)s.",
                 {'RDFGroup': rdf_group_no})

        return rdf_group_no, remote_array

    def failover_host(self, volumes, secondary_id=None, groups=None):
        """Fails over the volumes on a host back and forth.

        Driver needs to update following info for failed-over volume:
        1. provider_location: update array details
        2. replication_status: new status for replication-enabled volume
        :param volumes: the list of volumes to be failed over
        :param secondary_id: the target backend
        :param groups: replication groups
        :returns: secondary_id, volume_update_list, group_update_list
        :raises: InvalidReplicationTarget
        """
        volume_update_list = list()
        group_update_list = list()
        primary_array = self.configuration.safe_get(utils.POWERMAX_ARRAY)
        array_list = self.rest.get_arrays_list()
        is_valid, msg = self.utils.validate_failover_request(
            self.failover, secondary_id, self.rep_configs, primary_array,
            array_list, self.promotion)
        if not is_valid:
            LOG.error(msg)
            raise exception.InvalidReplicationTarget(msg)

        group_fo = None
        if not self.failover:
            self.failover = True
            if not secondary_id:
                secondary_id = utils.RDF_FAILEDOVER_STATE
        elif secondary_id == 'default':
            self.failover = False
            group_fo = 'default'

        if secondary_id == utils.PMAX_FAILOVER_START_ARRAY_PROMOTION:
            self.promotion = True
            LOG.info("Enabled array promotion.")
        else:
            volume_update_list, group_update_list = (
                self._populate_volume_and_group_update_lists(
                    volumes, groups, group_fo))

        if secondary_id == 'default' and self.promotion:
            self.promotion = False
            LOG.info("Disabled array promotion.")

        LOG.info("Failover host complete.")
        return secondary_id, volume_update_list, group_update_list

    def _populate_volume_and_group_update_lists(
            self, volumes, groups, group_fo):
        """Populate volume and group update lists

        :param volumes: the list of volumes to be failed over
        :param groups: replication groups
        :param group_fo: group fail over
        :returns: volume_update_list, group_update_list
        """
        volume_update_list = []
        group_update_list = []
        # Since we are updating volumes if a volume is in a group, copy to
        # a new variable otherwise we will be updating the replicated_vols
        # variable assigned in manager.py's failover method.
        vols = deepcopy(volumes)

        if groups:
            for group in groups:
                group_vol_list = []
                for index, vol in enumerate(vols):
                    if vol.group_id == group.id:
                        group_vol_list.append(vols[index])
                vols = [vol for vol in vols if vol not in group_vol_list]
                grp_update, vol_updates = (
                    self.failover_replication(
                        None, group, group_vol_list, group_fo, host=True))

                group_update_list.append({'group_id': group.id,
                                          'updates': grp_update})
                volume_update_list += vol_updates

        non_rep_vol_list, sync_vol_dict, async_vol_dict, metro_vol_list = (
            [], {}, {}, [])
        for volume in vols:
            array = ast.literal_eval(volume.provider_location)['array']
            extra_specs = self._initial_setup(volume)
            extra_specs[utils.ARRAY] = array
            if self.utils.is_replication_enabled(extra_specs):
                rep_mode = extra_specs.get(utils.REP_MODE, utils.REP_SYNC)
                backend_id = self._get_replicated_volume_backend_id(
                    volume)
                rep_config = self.utils.get_rep_config(
                    backend_id, self.rep_configs)

                if rep_mode == utils.REP_SYNC:
                    key = rep_config['rdf_group_label']
                    sync_vol_dict.setdefault(key, []).append(volume)
                elif rep_mode == utils.REP_ASYNC:
                    vol_grp_name = self.utils.get_rdf_management_group_name(
                        rep_config)
                    async_vol_dict.setdefault(vol_grp_name, []).append(volume)
                else:
                    metro_vol_list.append(volume)
            else:
                non_rep_vol_list.append(volume)

        if len(sync_vol_dict) > 0:
            for key, sync_vol_list in sync_vol_dict.items():
                vol_updates = (
                    self._update_volume_list_from_sync_vol_list(
                        sync_vol_list, group_fo))
                volume_update_list += vol_updates

        if len(async_vol_dict) > 0:
            for vol_grp_name, async_vol_list in async_vol_dict.items():
                __, vol_updates = self._failover_replication(
                    async_vol_list, None, vol_grp_name,
                    secondary_backend_id=group_fo, host=True)
                volume_update_list += vol_updates

        if len(metro_vol_list) > 0:
            __, vol_updates = (
                self._failover_replication(
                    metro_vol_list, None, None, secondary_backend_id=group_fo,
                    host=True, is_metro=True))
            volume_update_list += vol_updates

        if len(non_rep_vol_list) > 0:
            if self.promotion:
                # Volumes that were promoted will have a replication state
                # of error with no other replication metadata. Use this to
                # determine which volumes should updated to have a replication
                # state of disabled.
                for vol in non_rep_vol_list:
                    volume_update_list.append({
                        'volume_id': vol.id,
                        'updates': {
                            'replication_status': REPLICATION_DISABLED}})
            elif self.failover:
                # Since the array has been failed-over,
                # volumes without replication should be in error.
                for vol in non_rep_vol_list:
                    volume_update_list.append({
                        'volume_id': vol.id,
                        'updates': {'status': 'error'}})
        return volume_update_list, group_update_list

    def _update_volume_list_from_sync_vol_list(
            self, sync_vol_list, group_fo):
        """Update the volume update list from the synced volume list

        :param sync_vol_list: synced volume list
        :param group_fo: group fail over
        :returns: vol_updates
        """
        extra_specs = self._initial_setup(sync_vol_list[0])
        replication_details = ast.literal_eval(
            sync_vol_list[0].replication_driver_data)
        remote_array = replication_details.get(utils.ARRAY)
        extra_specs[utils.ARRAY] = remote_array
        temp_grp_name = self.utils.get_temp_failover_grp_name(
            extra_specs[utils.REP_CONFIG])
        self.provision.create_volume_group(
            remote_array, temp_grp_name, extra_specs)
        device_ids = self._get_volume_device_ids(
            sync_vol_list, remote_array, remote_volumes=True)
        self.masking.add_volumes_to_storage_group(
            remote_array, device_ids, temp_grp_name, extra_specs)
        __, vol_updates = (
            self._failover_replication(
                sync_vol_list, None, temp_grp_name,
                secondary_backend_id=group_fo, host=True))
        self.rest.delete_storage_group(remote_array, temp_grp_name)
        return vol_updates

    def _get_replication_extra_specs(self, extra_specs, rep_config):
        """Get replication extra specifications.

        Called when target array operations are necessary -
        on create, extend, etc and when volume is failed over.
        :param extra_specs: the extra specifications
        :param rep_config: the replication configuration
        :returns: repExtraSpecs - dict
        """
        if not self.utils.is_replication_enabled(extra_specs):
            # Skip this if the volume is not replicated
            return
        rep_extra_specs = deepcopy(extra_specs)
        rep_extra_specs[utils.ARRAY] = rep_config['array']
        rep_extra_specs[utils.SRP] = rep_config['srp']
        rep_extra_specs[utils.PORTGROUPNAME] = rep_config['portgroup']

        # Get the RDF Group label & number
        array = (rep_config[utils.ARRAY] if self.promotion else
                 extra_specs[utils.ARRAY])
        rep_extra_specs['rdf_group_label'] = rep_config['rdf_group_label']
        rdf_group_no, __ = self.get_rdf_details(
            array, rep_config)
        rep_extra_specs['rdf_group_no'] = rdf_group_no
        # Get the SRDF wait/retries settings
        rep_extra_specs['sync_retries'] = rep_config['sync_retries']
        rep_extra_specs['sync_interval'] = rep_config['sync_interval']

        if rep_config['mode'] == utils.REP_METRO:
            exempt = True if self.next_gen else False
            rep_extra_specs[utils.RDF_CONS_EXEMPT] = exempt
            bias = True if rep_config.get(utils.METROBIAS) else False
            rep_extra_specs[utils.METROBIAS] = bias

        # If disable compression is set, check if target array is all flash
        do_disable_compression = self.utils.is_compression_disabled(
            extra_specs)
        if do_disable_compression:
            if not self.rest.is_compression_capable(
                    rep_extra_specs[utils.ARRAY]):
                rep_extra_specs.pop(utils.DISABLECOMPRESSION, None)

        # Check to see if SLO and Workload are configured on the target array.
        rep_extra_specs['target_array_model'], next_gen = (
            self.rest.get_array_model_info(rep_config['array']))
        if extra_specs[utils.SLO]:
            is_valid_slo, is_valid_workload = (
                self.provision.verify_slo_workload(
                    rep_extra_specs[utils.ARRAY],
                    extra_specs[utils.SLO],
                    rep_extra_specs[utils.WORKLOAD], next_gen,
                    rep_extra_specs['target_array_model']))
            if not is_valid_slo:
                LOG.warning("The target array does not support the "
                            "storage pool setting for SLO %(slo)s, "
                            "setting to NONE.",
                            {'slo': extra_specs[utils.SLO]})
                rep_extra_specs[utils.SLO] = None
            if not is_valid_workload:
                LOG.warning("The target array does not support the "
                            "storage pool setting for workload "
                            "%(workload)s, setting to NONE.",
                            {'workload': extra_specs[utils.WORKLOAD]})
                rep_extra_specs[utils.WORKLOAD] = None
        return rep_extra_specs

    @staticmethod
    def get_secondary_stats_info(rep_config, array_info):
        """On failover, report on secondary array statistics.

        :param rep_config: the replication configuration
        :param array_info: the array info
        :returns: secondary_info - dict
        """
        secondary_info = array_info.copy()
        secondary_info['SerialNumber'] = six.text_type(rep_config['array'])
        secondary_info['srpName'] = rep_config['srp']
        return secondary_info

    def create_group(self, context, group):
        """Creates a generic volume group.

        :param context: the context
        :param group: the group object to be created
        :returns: dict -- modelUpdate
        :raises: VolumeBackendAPIException, NotImplementedError, InvalidInput
        """
        if (not volume_utils.is_group_a_cg_snapshot_type(group)
                and not group.is_replicated):
            raise NotImplementedError()

        # If volume types are added during creation, validate replication
        # extra_spec consistency across volume types.
        extra_specs_list = list()
        for volume_type_id in group.get('volume_type_ids'):
            vt_extra_specs = self.utils.get_volumetype_extra_specs(
                None, volume_type_id)
            extra_specs_list.append(vt_extra_specs)

        if group.is_replicated:
            self.utils.validate_replication_group_config(
                self.rep_configs, extra_specs_list)
        else:
            self.utils.validate_non_replication_group_config(extra_specs_list)

        model_update = {'status': fields.GroupStatus.AVAILABLE}

        LOG.info("Create generic volume group: %(group)s.",
                 {'group': group.id})

        vol_grp_name = self.utils.update_volume_group_name(group)

        try:
            array, interval_retries_dict = self._get_volume_group_info(group)
            self.provision.create_volume_group(
                array, vol_grp_name, interval_retries_dict)
            if group.is_replicated:
                LOG.debug("Group: %(group)s is a replication group.",
                          {'group': group.id})
                target_backend_id = extra_specs_list[0].get(
                    utils.REPLICATION_DEVICE_BACKEND_ID,
                    utils.BACKEND_ID_LEGACY_REP)
                target_rep_config = self.utils.get_rep_config(
                    target_backend_id, self.rep_configs)
                # Create remote group
                __, remote_array = self.get_rdf_details(
                    array, target_rep_config)
                self.provision.create_volume_group(
                    remote_array, vol_grp_name, interval_retries_dict)
                model_update.update({
                    'replication_status': fields.ReplicationStatus.ENABLED})
        except Exception:
            exception_message = (_("Failed to create generic volume group:"
                                   " %(volGrpName)s.")
                                 % {'volGrpName': vol_grp_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        return model_update

    def delete_group(self, context, group, volumes):
        """Deletes a generic volume group.

        :param context: the context
        :param group: the group object to be deleted
        :param volumes: the list of volumes in the generic group to be deleted
        :returns: dict -- modelUpdate
        :returns: list -- list of volume model updates
        :raises: NotImplementedError
        """
        LOG.info("Delete generic volume group: %(group)s.",
                 {'group': group.id})
        if (not volume_utils.is_group_a_cg_snapshot_type(group)
                and not group.is_replicated):
            raise NotImplementedError()
        model_update, volumes_model_update = self._delete_group(
            group, volumes)
        return model_update, volumes_model_update

    def _delete_group(self, group, volumes):
        """Helper function to delete a volume group.

        :param group: the group object
        :param volumes: the member volume objects
        :returns: model_update, volumes_model_update
        """
        volumes_model_update = []
        array, interval_retries_dict = self._get_volume_group_info(group)
        vol_grp_name = None

        volume_group = self._find_volume_group(
            array, group)

        if volume_group is None:
            LOG.error("Cannot find generic volume group %(volGrpName)s.",
                      {'volGrpName': group.id})
            model_update = {'status': fields.GroupStatus.DELETED}

            volumes_model_update = self.utils.update_volume_model_updates(
                volumes_model_update, volumes, group.id, status='deleted')
            return model_update, volumes_model_update

        if 'name' in volume_group:
            vol_grp_name = volume_group['name']
        volume_device_ids = self._get_members_of_volume_group(
            array, vol_grp_name)
        deleted_volume_device_ids = []

        # If volumes are being deleted along with the group, ensure snapshot
        # cleanup completes before doing any replication/storage group cleanup.
        remaining_device_snapshots = list()
        remaining_snapvx_targets = list()

        def _cleanup_snapshots(device_id):
            self._cleanup_device_snapvx(array, device_id, extra_specs)
            snapshots = self.rest.get_volume_snapshot_list(array, device_id)
            __, snapvx_target_details = self.rest.find_snap_vx_sessions(
                array, device_id, tgt_only=True)
            if snapshots:
                snapshot_names = ', '.join(
                    snap.get('snapshotName') for snap in snapshots)
                snap_details = {
                    'device_id': device_id, 'snapshot_names': snapshot_names}
                remaining_device_snapshots.append(snap_details)
            if snapvx_target_details:
                source_vol_id = snapvx_target_details.get('source_vol_id')
                snap_name = snapvx_target_details.get('snap_name')
                target_details = {
                    'device_id': device_id, 'source_vol_id': source_vol_id,
                    'snapshot_name': snap_name}
                remaining_snapvx_targets.append(target_details)

        vol_not_deleted = list()
        for vol in volumes:
            extra_specs = self._initial_setup(vol)
            device_id = self._find_device_on_array(vol, extra_specs)
            if device_id:
                _cleanup_snapshots(device_id)
            else:
                LOG.debug('Cannot find device id for volume.  It is '
                          'possible this information was not persisted.')
                vol_not_deleted.append(vol)
        if len(vol_not_deleted) == len(volume_device_ids):
            for volume_device_id in volume_device_ids:
                _cleanup_snapshots(volume_device_id)

        # Fail out if volumes to be deleted still have snapshots.
        if remaining_device_snapshots:
            for details in remaining_device_snapshots:
                device_id = details.get('device_id')
                snapshot_names = details.get('snapshot_names')
                LOG.error('Cannot delete device %s, it has the '
                          'following active snapshots, %s.',
                          device_id, snapshot_names)
            raise exception.VolumeBackendAPIException(_(
                'Group volumes have active snapshots. Cannot perform group '
                'delete. Wait for snapvx sessions to complete their '
                'processes or remove volumes from group before attempting '
                'to delete again. Please see previously logged error '
                'message for device and snapshot details.'))

        if remaining_snapvx_targets:
            for details in remaining_snapvx_targets:
                device_id = details.get('device_id')
                snap_name = details.get('snapshot_name')
                source_vol_id = details.get('source_vol_id')
                LOG.error('Cannot delete device %s, it is current a target '
                          'of snapshot %s with source device id %s',
                          device_id, snap_name, source_vol_id)
            raise exception.VolumeBackendAPIException(_(
                'Some group volumes are targets of a snapvx session. Cannot '
                'perform group delete. Wait for snapvx sessions to complete '
                'their processes or remove volumes from group before '
                'attempting to delete again. Please see previously logged '
                'error message for device and snapshot details.'))

        # Remove replication for group, if applicable
        if group.is_replicated:
            vt_extra_specs = self.utils.get_volumetype_extra_specs(
                None, group.get('volume_types')[0]['id'])
            target_backend_id = vt_extra_specs.get(
                utils.REPLICATION_DEVICE_BACKEND_ID,
                utils.BACKEND_ID_LEGACY_REP)
            target_rep_config = self.utils.get_rep_config(
                target_backend_id, self.rep_configs)
            self._cleanup_group_replication(
                array, vol_grp_name, volume_device_ids,
                interval_retries_dict, target_rep_config)
        try:
            if volume_device_ids:

                def _delete_vol(dev_id):
                    if group.is_replicated:
                        # Set flag to True if replicated.
                        extra_specs[utils.FORCE_VOL_EDIT] = True
                    if dev_id in volume_device_ids:
                        self.masking.remove_and_reset_members(
                            array, vol, dev_id, vol.name,
                            extra_specs, False)
                        self._delete_from_srp(
                            array, dev_id, "group vol", extra_specs)
                    else:
                        LOG.debug("Volume not found on the array.")
                    # Add the device id to the deleted list
                    deleted_volume_device_ids.append(dev_id)

                # First remove all the volumes from the SG
                self.masking.remove_volumes_from_storage_group(
                    array, volume_device_ids, vol_grp_name,
                    interval_retries_dict)
                for vol in volumes:
                    extra_specs = self._initial_setup(vol)
                    device_id = self._find_device_on_array(vol, extra_specs)
                    if device_id:
                        _delete_vol(device_id)
                if volume_device_ids != deleted_volume_device_ids:
                    new_list = list(set(volume_device_ids).difference(
                        deleted_volume_device_ids))
                    for device_id in new_list:
                        _delete_vol(device_id)

            # Once all volumes are deleted then delete the SG
            self.rest.delete_storage_group(array, vol_grp_name)
            model_update = {'status': fields.GroupStatus.DELETED}
            volumes_model_update = self.utils.update_volume_model_updates(
                volumes_model_update, volumes, group.id, status='deleted')
        except Exception as e:
            LOG.error("Error deleting volume group."
                      "Error received: %(e)s", {'e': e})
            model_update = {'status': fields.GroupStatus.ERROR_DELETING}
            volumes_model_update = self._handle_delete_group_exception(
                deleted_volume_device_ids, volume_device_ids, group.id, array,
                vol_grp_name, interval_retries_dict, volumes_model_update)

        return model_update, volumes_model_update

    def _handle_delete_group_exception(
            self, deleted_volume_device_ids, volume_device_ids, group_id,
            array, vol_grp_name, interval_retries_dict, volumes_model_update):
        """Handle delete group exception and update volume model

        :param deleted_volume_device_ids: deleted volume device ids
        :param volume_device_ids: volume device ids
        :param group_id: group id
        :param array: array serial number
        :param vol_grp_name: volume group name
        :param interval_retries_dict: intervals and retries dict
        :param volumes_model_update: volume model update dict
        :returns: volumes_model_update
        """
        # Update the volumes_model_update
        if deleted_volume_device_ids:
            LOG.debug("Device ids: %(dev)s are deleted.",
                      {'dev': deleted_volume_device_ids})
        volumes_not_deleted = []
        for vol in volume_device_ids:
            if vol not in deleted_volume_device_ids:
                volumes_not_deleted.append(vol)
        if not deleted_volume_device_ids:
            volumes_model_update = self.utils.update_volume_model_updates(
                volumes_model_update, deleted_volume_device_ids,
                group_id, status='deleted')
        if not volumes_not_deleted:
            volumes_model_update = self.utils.update_volume_model_updates(
                volumes_model_update, volumes_not_deleted,
                group_id, status='error_deleting')
        # As a best effort try to add back the undeleted volumes to sg
        # Don't throw any exception in case of failure
        try:
            if not volumes_not_deleted:
                self.masking.add_volumes_to_storage_group(
                    array, volumes_not_deleted,
                    vol_grp_name, interval_retries_dict)
        except Exception as ex:
            LOG.error("Error in rollback - %(ex)s. "
                      "Failed to add back volumes to sg %(sg_name)s",
                      {'ex': ex, 'sg_name': vol_grp_name})
        return volumes_model_update

    def _cleanup_group_replication(
            self, array, vol_grp_name, volume_device_ids, extra_specs,
            rep_config):
        """Cleanup remote replication.

        Break and delete the rdf replication relationship and
        delete the remote storage group and member devices.
        :param array: the array serial number
        :param vol_grp_name: the volume group name
        :param volume_device_ids: the device ids of the local volumes
        :param extra_specs: the extra specifications
        :param rep_config: the rep config to use for rdf operations
        """
        extra_specs[utils.FORCE_VOL_EDIT] = True
        rdf_group_no, remote_array = self.get_rdf_details(array, rep_config)
        # Delete replication for group, if applicable
        group_details = self.rest.get_storage_group_rep(
            array, vol_grp_name)
        if group_details and group_details.get('rdf', False):
            self.rest.srdf_suspend_replication(
                array, vol_grp_name, rdf_group_no, extra_specs)
            if volume_device_ids:
                LOG.debug("Deleting remote replication for group %(sg)s", {
                    'sg': vol_grp_name})
                self.rest.delete_storagegroup_rdf(array, vol_grp_name,
                                                  rdf_group_no)
        remote_device_ids = self._get_members_of_volume_group(
            remote_array, vol_grp_name)
        # Remove volumes from remote replication group
        if remote_device_ids:
            self.masking.remove_volumes_from_storage_group(
                remote_array, remote_device_ids, vol_grp_name, extra_specs)
        for device_id in remote_device_ids:
            # Make sure they are not members of any other storage groups
            self.masking.remove_and_reset_members(
                remote_array, None, device_id, 'target_vol',
                extra_specs, False)
            self._delete_from_srp(
                remote_array, device_id, "group vol", extra_specs)
        # Once all volumes are deleted then delete the SG
        if self.rest.get_storage_group(remote_array, vol_grp_name):
            self.rest.delete_storage_group(remote_array, vol_grp_name)

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a generic volume group snapshot.

        :param context: the context
        :param group_snapshot: the group snapshot to be created
        :param snapshots: snapshots
        :returns: dict -- modelUpdate
        :returns: list -- list of snapshots
        :raises: VolumeBackendAPIException, NotImplementedError
        """
        grp_id = group_snapshot.group_id
        source_group = group_snapshot.get('group')
        if not volume_utils.is_group_a_cg_snapshot_type(source_group):
            raise NotImplementedError()
        snapshots_model_update = []
        LOG.info(
            "Create snapshot for %(grpId)s "
            "group Snapshot ID: %(group_snapshot)s.",
            {'group_snapshot': group_snapshot.id,
             'grpId': grp_id})

        try:
            snap_name = self.utils.truncate_string(group_snapshot.id, 19)
            self._create_group_replica(source_group, snap_name)

        except Exception as e:
            exception_message = (_("Failed to create snapshot for group: "
                                   "%(volGrpName)s. Exception received: %(e)s")
                                 % {'volGrpName': grp_id,
                                    'e': six.text_type(e)})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        for snapshot in snapshots:
            src_dev_id = self._get_src_device_id_for_group_snap(snapshot)
            extra_specs = self._initial_setup(snapshot.volume)
            array = extra_specs['array']
            snapshot_model_dict = {
                'id': snapshot.id,
                'provider_location': six.text_type(
                    {'source_id': src_dev_id, 'snap_name': snap_name}),
                'status': fields.SnapshotStatus.AVAILABLE}

            snapshot_model_dict = self.update_metadata(
                snapshot_model_dict, snapshot.metadata,
                self.get_snapshot_metadata(
                    array, src_dev_id, snap_name))
            snapshots_model_update.append(snapshot_model_dict)
        model_update = {'status': fields.GroupStatus.AVAILABLE}

        return model_update, snapshots_model_update

    def _get_src_device_id_for_group_snap(self, snapshot):
        """Get the source device id for the provider_location.

        :param snapshot: the snapshot object
        :returns: src_device_id
        """
        volume = snapshot.volume
        extra_specs = self._initial_setup(volume)
        return self._find_device_on_array(volume, extra_specs)

    def _create_group_replica(
            self, source_group, snap_name):
        """Create a group replica.

        This can be a group snapshot or a cloned volume group.
        :param source_group: the group object
        :param snap_name: the name of the snapshot
        """
        array, interval_retries_dict = self._get_volume_group_info(
            source_group)
        vol_grp_name = None
        volume_group = (
            self._find_volume_group(array, source_group))
        if volume_group:
            if 'name' in volume_group:
                vol_grp_name = volume_group['name']
        if vol_grp_name is None:
            exception_message = (
                _("Cannot find generic volume group %(group_id)s.") %
                {'group_id': source_group.id})
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        self.provision.create_group_replica(
            array, vol_grp_name,
            snap_name, interval_retries_dict)

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Delete a volume group snapshot.

        :param context: the context
        :param group_snapshot: the volume group snapshot to be deleted
        :param snapshots: the snapshot objects
        :returns: model_update, snapshots_model_update
        """
        model_update, snapshots_model_update = self._delete_group_snapshot(
            group_snapshot, snapshots)
        return model_update, snapshots_model_update

    def _delete_group_snapshot(self, group_snapshot, snapshots):
        """Helper function to delete a group snapshot.

        :param group_snapshot: the group snapshot object
        :param snapshots: the snapshot objects
        :returns: model_update, snapshots_model_update
        :raises: VolumeBackendApiException, NotImplementedError
        """
        snapshots_model_update = []
        source_group = group_snapshot.get('group')
        grp_id = group_snapshot.group_id
        if not volume_utils.is_group_a_cg_snapshot_type(source_group):
            raise NotImplementedError()

        LOG.info("Delete snapshot grpSnapshotId: %(grpSnapshotId)s"
                 " for source group %(grpId)s",
                 {'grpSnapshotId': group_snapshot.id,
                  'grpId': grp_id})

        snap_name = self.utils.truncate_string(group_snapshot.id, 19)
        vol_grp_name = None
        try:
            # Get the array serial
            array, extra_specs = self._get_volume_group_info(
                source_group)
            # Get the volume group dict for getting the group name
            volume_group = (self._find_volume_group(array, source_group))
            if volume_group and volume_group.get('name'):
                vol_grp_name = volume_group['name']
            if vol_grp_name is None:
                exception_message = (
                    _("Cannot find generic volume group %(grp_id)s.") %
                    {'group_id': source_group.id})
                raise exception.VolumeBackendAPIException(
                    message=exception_message)

            self.provision.delete_group_replica(
                array, snap_name, vol_grp_name)

            model_update = {'status': fields.GroupSnapshotStatus.DELETED}
            for snapshot in snapshots:
                snapshots_model_update.append(
                    {'id': snapshot.id,
                     'status': fields.SnapshotStatus.DELETED})
        except Exception as e:
            LOG.error("Error deleting volume group snapshot."
                      "Error received: %(e)s", {'e': e})
            model_update = {
                'status': fields.GroupSnapshotStatus.ERROR_DELETING}

        return model_update, snapshots_model_update

    def _get_snap_src_dev_list(self, array, snapshots):
        """Get the list of source devices for a list of snapshots.

        :param array: the array serial number
        :param snapshots: the list of snapshot objects
        :returns: src_dev_ids
        """
        src_dev_ids = []
        for snap in snapshots:
            src_dev_id, snap_name, __ = self._parse_snap_info(array, snap)
            if snap_name:
                src_dev_ids.append(src_dev_id)
        return src_dev_ids

    def _find_volume_group(self, array, group):
        """Finds a volume group given the group.

        :param array: the array serial number
        :param group: the group object
        :returns: volume group dictionary
        """
        group_name = self.utils.update_volume_group_name(group)
        volume_group = self.rest.get_storage_group_rep(array, group_name)
        if not volume_group:
            LOG.warning("Volume group %(group_id)s cannot be found",
                        {'group_id': group_name})
            return None
        return volume_group

    def _get_members_of_volume_group(self, array, group_name):
        """Get the members of a volume group.

        :param array: the array serial number
        :param group_name: the storage group name
        :returns: list -- member_device_ids
        """
        member_device_ids = self.rest.get_volumes_in_storage_group(
            array, group_name)
        if not member_device_ids:
            LOG.info("No member volumes found in %(group_id)s",
                     {'group_id': group_name})
        return member_device_ids

    def update_group(self, group, add_volumes, remove_volumes):
        """Updates LUNs in generic volume group.

        :param group: storage configuration service instance
        :param add_volumes: the volumes uuids you want to add to the vol grp
        :param remove_volumes: the volumes uuids you want to remove from
                               the CG
        :returns: model_update
        :raises: VolumeBackendAPIException, NotImplementedError
        """
        LOG.info("Update generic volume Group: %(group)s. "
                 "This adds and/or removes volumes from "
                 "a generic volume group.",
                 {'group': group.id})
        if (not volume_utils.is_group_a_cg_snapshot_type(group)
                and not group.is_replicated):
            raise NotImplementedError()

        model_update = {'status': fields.GroupStatus.AVAILABLE}
        if self.promotion:
            self._update_group_promotion(
                group, add_volumes, remove_volumes)
        elif self.failover:
            msg = _('Cannot perform group updates during failover, please '
                    'either failback or perform a promotion operation.')
            raise exception.VolumeBackendAPIException(msg)
        else:
            array, interval_retries_dict = self._get_volume_group_info(group)
            add_vols = [vol for vol in add_volumes] if add_volumes else []
            add_device_ids = self._get_volume_device_ids(add_vols, array)
            remove_vols = [
                vol for vol in remove_volumes] if remove_volumes else []
            remove_device_ids = self._get_volume_device_ids(remove_vols, array)
            vol_grp_name = None
            try:
                volume_group = self._find_volume_group(array, group)
                if volume_group:
                    if 'name' in volume_group:
                        vol_grp_name = volume_group['name']
                if vol_grp_name is None:
                    raise exception.GroupNotFound(group_id=group.id)
                if group.is_replicated:
                    # Need force flag when manipulating RDF enabled SGs
                    interval_retries_dict[utils.FORCE_VOL_EDIT] = True
                # Add volume(s) to the group
                if add_device_ids:
                    self.utils.check_rep_status_enabled(group)
                    for vol in add_vols:
                        extra_specs = self._initial_setup(vol)
                        self.utils.check_replication_matched(vol, extra_specs)
                    self.masking.add_volumes_to_storage_group(
                        array, add_device_ids, vol_grp_name,
                        interval_retries_dict)
                    if group.is_replicated:
                        # Add remote volumes to remote storage group
                        self.masking.add_remote_vols_to_volume_group(
                            add_vols, group, interval_retries_dict)
                # Remove volume(s) from the group
                if remove_device_ids:
                    # Check if the volumes exist in the storage group
                    temp_list = deepcopy(remove_device_ids)
                    for device_id in temp_list:
                        if not self.rest.is_volume_in_storagegroup(
                                array, device_id, vol_grp_name):
                            remove_device_ids.remove(device_id)
                    if remove_device_ids:
                        self.masking.remove_volumes_from_storage_group(
                            array, remove_device_ids,
                            vol_grp_name, interval_retries_dict)
                    if group.is_replicated:
                        # Remove remote volumes from the remote storage group
                        self._remove_remote_vols_from_volume_group(
                            array, remove_vols, group, interval_retries_dict)
            except exception.GroupNotFound:
                raise
            except Exception as ex:
                exception_message = (_("Failed to update volume group:"
                                       " %(volGrpName)s. Exception: %(ex)s.")
                                     % {'volGrpName': group.id,
                                        'ex': ex})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    message=exception_message)

            self.volume_metadata.capture_modify_group(
                vol_grp_name, group.id, add_vols, remove_volumes, array)

        return model_update, None, None

    def _update_group_promotion(self, group, add_volumes, remove_volumes):
        """Updates LUNs in generic volume group during array promotion.

        :param group: storage configuration service instance
        :param add_volumes: the volumes uuids you want to add to the vol grp
        :param remove_volumes: the volumes uuids you want to remove from
                               the CG
        :returns: model_update
        :raises: VolumeBackendAPIException
        """
        if not group.is_replicated:
            msg = _('Group updates are only supported on replicated volume '
                    'groups during failover promotion.')
            raise exception.VolumeBackendAPIException(msg)
        if add_volumes:
            msg = _('Unable to add to volumes to a group, only volume '
                    'removal is supported during promotion.')
            raise exception.VolumeBackendAPIException(msg)

        # Either add_volumes or remove_volumes must be provided, if add_volumes
        # then excep is raised, other there must be remove_volumes present
        volume = remove_volumes[0]
        extra_specs = self._initial_setup(volume, volume.volume_type_id)
        rep_extra_specs = self._get_replication_extra_specs(
            extra_specs, extra_specs[utils.REP_CONFIG])
        remote_array = rep_extra_specs['array']

        vol_grp_name = None
        volume_group = self._find_volume_group(remote_array, group)
        if volume_group:
            if 'name' in volume_group:
                vol_grp_name = volume_group['name']
        if vol_grp_name is None:
            raise exception.GroupNotFound(group_id=group.id)

        interval_retries_dict = {
            utils.INTERVAL: self.interval, utils.RETRIES: self.retries}
        # Volumes have already failed over and had their provider_location
        # updated, do not get remote device IDs here
        remove_device_ids = self._get_volume_device_ids(
            remove_volumes, remote_array)
        if remove_device_ids:
            interval_retries_dict[utils.FORCE_VOL_EDIT] = True
            # Check if the volumes exist in the storage group
            temp_list = deepcopy(remove_device_ids)
            for device_id in temp_list:
                if not self.rest.is_volume_in_storagegroup(
                        remote_array, device_id, vol_grp_name):
                    remove_device_ids.remove(device_id)
            if remove_device_ids:
                self.masking.remove_volumes_from_storage_group(
                    remote_array, remove_device_ids,
                    vol_grp_name, interval_retries_dict)
            self.volume_metadata.capture_modify_group(
                vol_grp_name, group.id, list(), remove_volumes, remote_array)

    def _remove_remote_vols_from_volume_group(
            self, array, volumes, group, extra_specs):
        """Remove the remote volumes from their volume group.

        :param array: the array serial number
        :param volumes: list of volumes
        :param group: the id of the group
        :param extra_specs: the extra specifications
        """
        remote_device_list = []
        backend_id = self._get_replicated_volume_backend_id(volumes[0])
        rep_config = self.utils.get_rep_config(backend_id, self.rep_configs)
        __, remote_array = self.get_rdf_details(array, rep_config)
        for vol in volumes:
            remote_loc = ast.literal_eval(vol.replication_driver_data)
            founddevice_id = self.rest.check_volume_device_id(
                remote_array, remote_loc['device_id'], vol.id)
            if founddevice_id is not None:
                remote_device_list.append(founddevice_id)
        group_name = self.provision.get_or_create_volume_group(
            array, group, extra_specs)
        self.masking.remove_volumes_from_storage_group(
            remote_array, remote_device_list, group_name, extra_specs)
        LOG.info("Removed volumes from remote volume group.")

    def _get_volume_device_ids(self, volumes, array, remote_volumes=False):
        """Get volume device ids from volume.

        :param volumes: volume objects
        :param array: array id
        :param remote_volumes: get the remote ids for replicated volumes
        :returns: device_ids
        """
        device_ids = []
        for volume in volumes:
            if remote_volumes:
                replication_details = ast.literal_eval(
                    volume.replication_driver_data)
                remote_array = replication_details.get(utils.ARRAY)
                specs = {utils.ARRAY: remote_array}
                device_id = self._find_device_on_array(
                    volume, specs, remote_volumes)
            else:
                specs = {utils.ARRAY: array}
                device_id = self._find_device_on_array(volume, specs)
            if device_id is None:
                LOG.error("Volume %(name)s not found on the array.",
                          {'name': volume['name']})
            else:
                device_ids.append(device_id)
        return device_ids

    def create_group_from_src(self, context, group, volumes,
                              group_snapshot, snapshots, source_group,
                              source_vols):
        """Creates the volume group from source.

        :param context: the context
        :param group: the volume group object to be created
        :param volumes: volumes in the consistency group
        :param group_snapshot: the source volume group snapshot
        :param snapshots: snapshots of the source volumes
        :param source_group: the source volume group
        :param source_vols: the source vols
        :returns: model_update, volumes_model_update
                  model_update is a dictionary of cg status
                  volumes_model_update is a list of dictionaries of volume
                  update
        :raises: VolumeBackendAPIException, NotImplementedError
        """
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        create_snapshot = False
        volumes_model_update = []
        if group_snapshot:
            source_id = group_snapshot.id
            actual_source_grp = group_snapshot.get('group')
        elif source_group:
            source_id = source_group.id
            actual_source_grp = source_group
            create_snapshot = True
        else:
            exception_message = (_("Must supply either group snapshot or "
                                   "a source group."))
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        tgt_name = self.utils.update_volume_group_name(group)
        rollback_dict = {}
        array, interval_retries_dict = self._get_volume_group_info(group)
        source_sg = self._find_volume_group(array, actual_source_grp)
        if source_sg is not None:
            src_grp_name = (source_sg['name']
                            if 'name' in source_sg else None)
            rollback_dict['source_group_name'] = src_grp_name
        else:
            error_msg = (_("Cannot retrieve source volume group %(grp_id)s "
                           "from the array.")
                         % {'grp_id': actual_source_grp.id})
            LOG.error(error_msg)
            raise exception.VolumeBackendAPIException(message=error_msg)

        LOG.debug("Enter PowerMax/VMAX create_volume group_from_src. Group "
                  "to be created: %(grpId)s, Source : %(SourceGrpId)s.",
                  {'grpId': group.id, 'SourceGrpId': source_id})

        try:
            self.provision.create_volume_group(
                array, tgt_name, interval_retries_dict)
            rollback_dict.update({
                'target_group_name': tgt_name, 'volumes': [],
                'device_ids': [], 'list_volume_pairs': [],
                'interval_retries_dict': interval_retries_dict})
            model_update = {'status': fields.GroupStatus.AVAILABLE}
            # Create the target devices
            list_volume_pairs = []
            for volume in volumes:
                (volumes_model_update, rollback_dict, list_volume_pairs,
                 extra_specs) = (
                    self._create_vol_and_add_to_group(
                        volume, group, tgt_name, rollback_dict,
                        source_vols, snapshots, list_volume_pairs,
                        volumes_model_update))

            snap_name, rollback_dict = (
                self._create_group_replica_and_get_snap_name(
                    group.id, actual_source_grp, source_id, source_sg,
                    rollback_dict, create_snapshot))

            # Link and break the snapshot to the source group
            snap_id_list = self.rest.get_storage_group_snap_id_list(
                array, src_grp_name, snap_name)
            if snap_id_list:
                if group.is_replicated:
                    interval_retries_dict[utils.FORCE_VOL_EDIT] = True
                self.provision.link_and_break_replica(
                    array, src_grp_name, tgt_name, snap_name,
                    interval_retries_dict, list_volume_pairs,
                    delete_snapshot=create_snapshot, snap_id=snap_id_list[0])

            # Update the replication status
            if group.is_replicated:
                backend = self._get_replicated_volume_backend_id(volumes[0])
                rep_config = self.utils.get_rep_config(
                    backend, self.rep_configs)
                interval_retries_dict[utils.REP_CONFIG] = rep_config
                volumes_model_update = self._replicate_group(
                    array, volumes_model_update,
                    tgt_name, interval_retries_dict)
                # Add the volumes to the default storage group
                extra_specs[utils.FORCE_VOL_EDIT] = True
                self._add_replicated_volumes_to_default_storage_group(
                    array, volumes_model_update, extra_specs)
                model_update.update({
                    'replication_status': fields.ReplicationStatus.ENABLED})
        except Exception:
            exception_message = (_("Failed to create vol grp %(volGrpName)s"
                                   " from source %(grpSnapshot)s.")
                                 % {'volGrpName': group.id,
                                    'grpSnapshot': source_id})
            LOG.error(exception_message)
            if array is not None:
                LOG.info("Attempting rollback for the create group from src.")
                self._rollback_create_group_from_src(array, rollback_dict)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        return model_update, volumes_model_update

    def _add_replicated_volumes_to_default_storage_group(
            self, array, volumes_model_update, extra_specs):
        """Add replicated volumes to the default storage group.

        :param array: the serial number of the array
        :param volumes_model_update: the list of volume updates
        :param extra_specs: the extra specifications
        """
        is_re = False
        rep_mode = None
        if self.utils.is_replication_enabled(extra_specs):
            is_re, rep_mode = True, extra_specs['rep_mode']
        do_disable_compression = self.utils.is_compression_disabled(
            extra_specs)
        storage_group_name = self.masking.get_or_create_default_storage_group(
            array, extra_specs[utils.SRP], extra_specs[utils.SLO],
            extra_specs[utils.WORKLOAD], extra_specs,
            do_disable_compression, is_re, rep_mode)
        local_device_list = list()
        remote_device_list = list()
        for volume_dict in volumes_model_update:
            if volume_dict.get('provider_location'):
                loc = ast.literal_eval(volume_dict.get('provider_location'))
                device_id = loc.get('device_id')
                local_array = loc.get('array')
                local_device_list.append(device_id)

            if volume_dict.get('replication_driver_data'):
                loc = ast.literal_eval(volume_dict.get(
                    'replication_driver_data'))
                remote_device_id = loc.get('device_id')
                remote_array = loc.get('array')
                remote_device_list.append(remote_device_id)
        if local_device_list:
            self.masking.add_volumes_to_storage_group(
                local_array, local_device_list, storage_group_name,
                extra_specs)
        if remote_device_list:
            self.masking.add_volumes_to_storage_group(
                remote_array, remote_device_list, storage_group_name,
                extra_specs)

    def _create_group_replica_and_get_snap_name(
            self, group_id, actual_source_grp, source_id, source_sg,
            rollback_dict, create_snapshot):
        """Create group replica and get snap name

        :param group_id: the group id
        :param actual_source_grp: the source group
        :param source_id: source id
        :param source_sg: source storage goup
        :param rollback_dict: rollback dict
        :param create_snapshot: boolean
        :returns: snap_name, rollback_dict
        """
        if create_snapshot is True:
            # We have to create a snapshot of the source group
            snap_name = self.utils.truncate_string(group_id, 19)
            self._create_group_replica(actual_source_grp, snap_name)
            rollback_dict['snap_name'] = snap_name
        else:
            # We need to check if the snapshot exists
            snap_name = self.utils.truncate_string(source_id, 19)
            if ('snapVXSnapshots' in source_sg and
                    snap_name in source_sg['snapVXSnapshots']):
                LOG.info("Snapshot is present on the array")
            else:
                error_msg = (_("Cannot retrieve source snapshot %(snap_id)s "
                               "from the array.") % {'snap_id': source_id})
                LOG.error(error_msg)
                raise exception.VolumeBackendAPIException(
                    message=error_msg)
        return snap_name, rollback_dict

    def _create_vol_and_add_to_group(
            self, volume, group, tgt_name, rollback_dict, source_vols,
            snapshots, list_volume_pairs, volumes_model_update):
        """Creates the volume group from source.

        :param volume: volume object
        :param group: the group object
        :param tgt_name: target name
        :param rollback_dict: rollback dict
        :param source_vols: source volumes
        :param snapshots: snapshot objects
        :param list_volume_pairs: volume pairs list
        :param volumes_model_update: volume model update
        :returns: volumes_model_update, rollback_dict, list_volume_pairs
                  extra_specs
        """

        src_dev_id, extra_specs, vol_size, tgt_vol_name = (
            self._get_clone_vol_info(
                volume, source_vols, snapshots))
        array = extra_specs[utils.ARRAY]
        volume_name = self.utils.get_volume_element_name(volume.id)
        if group.is_replicated:
            volume_dict = self._create_non_replicated_volume(
                array, volume, volume_name, tgt_name,
                vol_size, extra_specs)
            device_id = volume_dict['device_id']
        else:
            volume_dict, __, __, = self._create_volume(
                volume, tgt_vol_name, vol_size, extra_specs)
            device_id = volume_dict['device_id']
            # Add the volume to the volume group SG
            self.masking.add_volume_to_storage_group(
                extra_specs[utils.ARRAY], device_id, tgt_name,
                tgt_vol_name, extra_specs)
        # Record relevant information
        list_volume_pairs.append((src_dev_id, device_id))
        # Add details to rollback dict
        rollback_dict['device_ids'].append(device_id)
        rollback_dict['list_volume_pairs'].append(
            (src_dev_id, device_id))
        rollback_dict['volumes'].append(
            (device_id, extra_specs, volume))
        volumes_model_update.append(
            self.utils.get_grp_volume_model_update(
                volume, volume_dict, group.id,
                meta=self.get_volume_metadata(volume_dict['array'],
                                              volume_dict['device_id'])))

        return (volumes_model_update, rollback_dict, list_volume_pairs,
                extra_specs)

    def _get_clone_vol_info(self, volume, source_vols, snapshots):
        """Get the clone volume info.

        :param volume: the new volume object
        :param source_vols: the source volume list
        :param snapshots: the source snapshot list
        :returns: src_dev_id, extra_specs, vol_size, tgt_vol_name
        """
        src_dev_id, vol_size = None, None
        extra_specs = self._initial_setup(volume)
        if not source_vols:
            for snap in snapshots:
                if snap.id == volume.snapshot_id:
                    src_dev_id, __, __ = self._parse_snap_info(
                        extra_specs[utils.ARRAY], snap)
                    vol_size = snap.volume_size
        else:
            for src_vol in source_vols:
                if src_vol.id == volume.source_volid:
                    src_extra_specs = self._initial_setup(src_vol)
                    src_dev_id = self._find_device_on_array(
                        src_vol, src_extra_specs)
                    vol_size = src_vol.size
        tgt_vol_name = self.utils.get_volume_element_name(volume.id)
        return src_dev_id, extra_specs, vol_size, tgt_vol_name

    def _rollback_create_group_from_src(self, array, rollback_dict):
        """Performs rollback for create group from src in case of failure.

        :param array: the array serial number
        :param rollback_dict: dict containing rollback details
        """
        try:
            # Delete the snapshot if required
            if rollback_dict.get("snap_name"):
                try:
                    self.provision.delete_group_replica(
                        array, rollback_dict["snap_name"],
                        rollback_dict["source_group_name"])
                except Exception as e:
                    LOG.debug("Failed to delete group snapshot. Attempting "
                              "further rollback. Exception received: %(e)s.",
                              {'e': e})
            if rollback_dict.get('volumes'):
                # Remove any devices which were added to the target SG
                if rollback_dict['device_ids']:
                    self.masking.remove_volumes_from_storage_group(
                        array, rollback_dict['device_ids'],
                        rollback_dict['target_group_name'],
                        rollback_dict['interval_retries_dict'])
                # Delete all the volumes
                for dev_id, extra_specs, volume in rollback_dict['volumes']:
                    self._remove_vol_and_cleanup_replication(
                        array, dev_id, "group vol", extra_specs, volume)
                    self._delete_from_srp(
                        array, dev_id, "group vol", extra_specs)
            # Delete the target SG
            if rollback_dict.get("target_group_name"):
                self.rest.delete_storage_group(
                    array, rollback_dict['target_group_name'])
            LOG.info("Rollback completed for create group from src.")
        except Exception as e:
            LOG.error("Rollback failed for the create group from src. "
                      "Exception received: %(e)s.", {'e': e})

    def _replicate_group(self, array, volumes_model_update,
                         group_name, extra_specs):
        """Replicate a cloned volume group.

        :param array: the array serial number
        :param volumes_model_update: the volumes model updates
        :param group_name: the group name
        :param extra_specs: the extra specs
        :returns: volumes_model_update
        """
        ret_volumes_model_update = []
        rdf_group_no, remote_array = self.get_rdf_details(
            array, extra_specs[utils.REP_CONFIG])
        self.rest.replicate_group(
            array, group_name, rdf_group_no, remote_array, extra_specs)
        # Need to set SRP to None for remote generic volume group - Not set
        # automatically, and a volume can only be in one storage group
        # managed by FAST
        self.rest.set_storagegroup_srp(
            remote_array, group_name, "None", extra_specs)
        for volume_model_update in volumes_model_update:
            vol_id = volume_model_update['id']
            loc = ast.literal_eval(volume_model_update['provider_location'])
            src_device_id = loc['device_id']
            rdf_vol_details = self.rest.get_rdf_group_volume(
                array, src_device_id)
            tgt_device_id = rdf_vol_details['remoteDeviceID']
            element_name = self.utils.get_volume_element_name(vol_id)
            self.rest.rename_volume(remote_array, tgt_device_id, element_name)
            rep_update = {'device_id': tgt_device_id, 'array': remote_array}
            volume_model_update.update(
                {'replication_driver_data': six.text_type(rep_update),
                 'replication_status': fields.ReplicationStatus.ENABLED})
            volume_model_update = self.update_metadata(
                volume_model_update, None, self.get_volume_metadata(
                    array, src_device_id))
            ret_volumes_model_update.append(volume_model_update)
        return ret_volumes_model_update

    def enable_replication(self, context, group, volumes):
        """Enable replication for a group.

        Replication is enabled on replication-enabled groups by default.
        :param context: the context
        :param group: the group object
        :param volumes: the list of volumes
        :returns: model_update, None
        """
        if not group.is_replicated:
            raise NotImplementedError()

        model_update = {}
        if not volumes:
            # Return if empty group
            return model_update, None

        try:
            vol_grp_name = None
            extra_specs = self._initial_setup(volumes[0])
            array = extra_specs[utils.ARRAY]
            volume_group = self._find_volume_group(array, group)
            if volume_group:
                if 'name' in volume_group:
                    vol_grp_name = volume_group['name']
            if vol_grp_name is None:
                raise exception.GroupNotFound(group_id=group.id)

            rdf_group_no, __ = self.get_rdf_details(
                array, extra_specs[utils.REP_CONFIG])
            self.rest.srdf_resume_replication(
                array, vol_grp_name, rdf_group_no, extra_specs)
            model_update.update({
                'replication_status': fields.ReplicationStatus.ENABLED})
        except Exception as e:
            model_update.update({
                'replication_status': fields.ReplicationStatus.ERROR})
            LOG.error("Error enabling replication on group %(group)s. "
                      "Exception received: %(e)s.",
                      {'group': group.id, 'e': e})

        return model_update, None

    def disable_replication(self, context, group, volumes):
        """Disable replication for a group.

        :param context: the context
        :param group: the group object
        :param volumes: the list of volumes
        :returns: model_update, None
        """
        if not group.is_replicated:
            raise NotImplementedError()

        model_update = {}
        if not volumes:
            # Return if empty group
            return model_update, None

        try:
            vol_grp_name = None
            extra_specs = self._initial_setup(volumes[0])
            array = extra_specs[utils.ARRAY]
            volume_group = self._find_volume_group(array, group)
            if volume_group:
                if 'name' in volume_group:
                    vol_grp_name = volume_group['name']
            if vol_grp_name is None:
                raise exception.GroupNotFound(group_id=group.id)

            rdf_group_no, __ = self.get_rdf_details(
                array, extra_specs[utils.REP_CONFIG])
            self.rest.srdf_suspend_replication(
                array, vol_grp_name, rdf_group_no, extra_specs)
            model_update.update({
                'replication_status': fields.ReplicationStatus.DISABLED})
        except Exception as e:
            model_update.update({
                'replication_status': fields.ReplicationStatus.ERROR})
            LOG.error("Error disabling replication on group %(group)s. "
                      "Exception received: %(e)s.",
                      {'group': group.id, 'e': e})

        return model_update, None

    def failover_replication(self, context, group, volumes,
                             secondary_backend_id=None, host=False):
        """Failover replication for a group.

        :param context: the context
        :param group: the group object
        :param volumes: the list of volumes
        :param secondary_backend_id: the secondary backend id - default None
        :param host: flag to indicate if whole host is being failed over
        :returns: model_update, vol_model_updates
        """
        return self._failover_replication(
            volumes, group, None,
            secondary_backend_id=secondary_backend_id, host=host)

    def _failover_replication(
            self, volumes, group, vol_grp_name,
            secondary_backend_id=None, host=False, is_metro=False):
        """Failover replication for a group.

        :param volumes: the list of volumes
        :param group: the group object
        :param vol_grp_name: the group name
        :param secondary_backend_id: the secondary backend id - default None
        :param host: flag to indicate if whole host is being failed over
        :returns: model_update, vol_model_updates
        """
        model_update, vol_model_updates = dict(), list()
        if not volumes:
            # Return if empty group
            return model_update, vol_model_updates

        extra_specs = self._initial_setup(volumes[0])
        replication_details = ast.literal_eval(
            volumes[0].replication_driver_data)
        remote_array = replication_details.get(utils.ARRAY)
        extra_specs[utils.ARRAY] = remote_array
        failover = False if secondary_backend_id == 'default' else True

        try:
            rdf_group_no, __ = self.get_rdf_details(
                remote_array, extra_specs[utils.REP_CONFIG])
            if group:
                volume_group = self._find_volume_group(remote_array, group)
                if volume_group:
                    if 'name' in volume_group:
                        vol_grp_name = volume_group['name']
                if vol_grp_name is None:
                    raise exception.GroupNotFound(group_id=group.id)

            is_partitioned = self._rdf_vols_partitioned(
                remote_array, volumes, rdf_group_no)

            if not is_metro and not is_partitioned:
                if failover:
                    self.rest.srdf_failover_group(
                        remote_array, vol_grp_name, rdf_group_no, extra_specs)
                else:
                    self.rest.srdf_failback_group(
                        remote_array, vol_grp_name, rdf_group_no, extra_specs)

            if failover:
                model_update.update({
                    'replication_status':
                        fields.ReplicationStatus.FAILED_OVER})
                vol_rep_status = fields.ReplicationStatus.FAILED_OVER
            else:
                model_update.update({
                    'replication_status': fields.ReplicationStatus.ENABLED})
                vol_rep_status = fields.ReplicationStatus.ENABLED

        except Exception as e:
            model_update.update({
                'replication_status': fields.ReplicationStatus.ERROR})
            vol_rep_status = fields.ReplicationStatus.ERROR
            LOG.error("Error failover replication on group %(group)s. "
                      "Exception received: %(e)s.",
                      {'group': vol_grp_name, 'e': e})

        for vol in volumes:
            loc = vol.provider_location
            rep_data = vol.replication_driver_data
            if vol_rep_status != fields.ReplicationStatus.ERROR:
                loc = vol.replication_driver_data
                rep_data = vol.provider_location
                local = ast.literal_eval(loc)
                remote = ast.literal_eval(rep_data)
                self.volume_metadata.capture_failover_volume(
                    vol, local['device_id'], local['array'], rdf_group_no,
                    remote['device_id'], remote['array'], extra_specs,
                    failover, vol_grp_name, vol_rep_status,
                    extra_specs[utils.REP_MODE])

            update = {'id': vol.id,
                      'replication_status': vol_rep_status,
                      'provider_location': loc,
                      'replication_driver_data': rep_data}
            if host:
                update = {'volume_id': vol.id, 'updates': update}
            vol_model_updates.append(update)

        LOG.debug("Volume model updates: %s", vol_model_updates)
        return model_update, vol_model_updates

    def _rdf_vols_partitioned(self, array, volumes, rdfg):
        """Check if rdf volumes have been failed over by powermax array

        :param array: remote array
        :param volumes: rdf volumes
        :param rdfg: rdf group
        :return: devices have partitioned states
        """
        is_partitioned = False
        for volume in volumes:
            if self.promotion:
                vol_data = volume.provider_location
            else:
                vol_data = volume.replication_driver_data
            vol_data = ast.literal_eval(vol_data)
            device_id = vol_data.get(utils.DEVICE_ID)
            vol_details = self.rest.get_rdf_pair_volume(array, rdfg, device_id)
            rdf_pair_state = vol_details.get(utils.RDF_PAIR_STATE, '').lower()
            if rdf_pair_state in utils.RDF_PARTITIONED_STATES:
                is_partitioned = True
                break
        return is_partitioned

    def get_attributes_from_cinder_config(self):
        """Get all attributes from the configuration file

        :returns: kwargs
        """
        kwargs = None
        username = self.configuration.safe_get(utils.VMAX_USER_NAME)
        password = self.configuration.safe_get(utils.VMAX_PASSWORD)
        if username and password:
            serial_number = self.configuration.safe_get(utils.POWERMAX_ARRAY)
            if serial_number is None:
                msg = _("Powermax Array Serial must be set in cinder.conf")
                LOG.error(msg)
                raise exception.InvalidConfigurationValue(message=msg)
            srp_name = self.configuration.safe_get(utils.POWERMAX_SRP)
            if srp_name is None:
                msg = _("Powermax SRP must be set in cinder.conf")
                LOG.error(msg)
                raise exception.InvalidConfigurationValue(message=msg)
            slo = self.configuration.safe_get(utils.POWERMAX_SERVICE_LEVEL)
            workload = self.configuration.safe_get(utils.VMAX_WORKLOAD)
            port_groups = self.configuration.safe_get(
                utils.POWERMAX_PORT_GROUPS)

            kwargs = (
                {'RestServerIp': self.configuration.safe_get(
                    utils.VMAX_SERVER_IP),
                 'RestServerPort': self._get_unisphere_port(),
                 'RestUserName': username,
                 'RestPassword': password,
                 'SerialNumber': serial_number,
                 'srpName': srp_name,
                 'PortGroup': port_groups})

            if self.configuration.safe_get('driver_ssl_cert_verify'):
                if self.configuration.safe_get('driver_ssl_cert_path'):
                    kwargs.update({'SSLVerify': self.configuration.safe_get(
                        'driver_ssl_cert_path')})
                else:
                    kwargs.update({'SSLVerify': True})
            else:
                kwargs.update({'SSLVerify': False})

            if slo:
                kwargs.update({'ServiceLevel': slo, 'Workload': workload})

        return kwargs

    def _get_volume_group_info(self, group):
        """Get the volume group array, retries and intervals

        :param group: the group object
        :returns: array -- str
                  interval_retries_dict -- dict
        """
        array, interval_retries_dict = self.utils.get_volume_group_utils(
            group, self.interval, self.retries)
        if not array:
            array = self.configuration.safe_get(utils.POWERMAX_ARRAY)
            if not array:
                exception_message = _(
                    "Cannot get the array serial_number")

                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    message=exception_message)
        return array, interval_retries_dict

    def _get_unisphere_port(self):
        """Get unisphere port from the configuration file

        :returns: unisphere port
        """
        if self.configuration.safe_get(utils.U4P_SERVER_PORT):
            return self.configuration.safe_get(utils.U4P_SERVER_PORT)
        else:
            LOG.debug("PowerMax/VMAX port is not set, using default port: %s",
                      utils.DEFAULT_PORT)
            return utils.DEFAULT_PORT

    def revert_to_snapshot(self, volume, snapshot):
        """Revert volume to snapshot.

        :param volume: the volume object
        :param snapshot: the snapshot object
        """
        extra_specs = self._initial_setup(volume)
        if self.utils.is_replication_enabled(extra_specs):
            exception_message = (_(
                "Volume is replicated - revert to snapshot feature is not "
                "supported for replicated volumes."))
            LOG.error(exception_message)
            raise exception.VolumeDriverException(message=exception_message)
        array = extra_specs[utils.ARRAY]
        sourcedevice_id, snap_name, snap_id_list = self._parse_snap_info(
            array, snapshot)
        if not sourcedevice_id or not snap_name:
            LOG.error("No snapshot found on the array")
            exception_message = (_(
                "Failed to revert the volume to the snapshot"))
            raise exception.VolumeDriverException(message=exception_message)
        if len(snap_id_list) != 1:
            exception_message = (_(
                "It is not possible to revert snapshot because there are "
                "either multiple or no snapshots associated with "
                "%(snap_name)s.") % {'snap_name': snap_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        else:
            snap_id = snap_id_list[0]
        self._cleanup_device_snapvx(array, sourcedevice_id, extra_specs)
        try:
            LOG.info("Reverting device: %(deviceid)s "
                     "to snapshot: %(snapname)s.",
                     {'deviceid': sourcedevice_id, 'snapname': snap_name})
            self.provision.revert_volume_snapshot(
                array, sourcedevice_id, snap_name, snap_id, extra_specs)
            # Once the restore is done, we need to check if it is complete
            restore_complete = self.provision.is_restore_complete(
                array, sourcedevice_id, snap_name, snap_id, extra_specs)
            if not restore_complete:
                LOG.debug("Restore couldn't complete in the specified "
                          "time interval. The terminate restore may fail")
            LOG.debug("Terminating restore session")
            # This may throw an exception if restore_complete is False
            self.provision.delete_volume_snap(
                array, snap_name, sourcedevice_id, snap_id,
                restored=True)
            # Revert volume to snapshot is successful if termination was
            # successful - possible even if restore_complete was False
            # when we checked last.
            LOG.debug("Restored session was terminated")
            LOG.info("Reverted the volume to snapshot successfully")
        except Exception as e:
            exception_message = (_(
                "Failed to revert the volume to the snapshot. "
                "Exception received was %(e)s") % {'e': six.text_type(e)})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

    def update_metadata(
            self, model_update, existing_metadata, new_metadata):
        """Update volume metadata in model_update.

        :param model_update: existing model
        :param existing_metadata: existing metadata
        :param new_metadata: new object metadata
        :returns: dict -- updated model
        """
        if existing_metadata:
            self._is_dict(existing_metadata, 'existing metadata')
        else:
            existing_metadata = dict()

        if model_update:
            self._is_dict(model_update, 'existing model')
            if 'metadata' in model_update:
                model_update['metadata'].update(existing_metadata)
            else:
                model_update.update({'metadata': existing_metadata})
        else:
            model_update = {}
            model_update.update({'metadata': existing_metadata})

        if new_metadata:
            self._is_dict(new_metadata, 'new object metadata')
            model_update['metadata'].update(new_metadata)

        return model_update

    def _is_dict(self, input, description):
        """Check that the input is a dict

        :param input: object for checking
        :raises: VolumeBackendAPIException
        """
        if not isinstance(input, dict):
            exception_message = (_(
                "Input %(desc)s is not a dict.") % {'desc': description})

            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

    def get_volume_metadata(self, array, device_id):
        """Get volume metadata for model_update.

        :param array: the array ID
        :param device_id: the device ID
        :returns: dict -- volume metadata
        """
        vol_info = self.rest._get_private_volume(array, device_id)
        vol_header = vol_info['volumeHeader']
        array_model, __ = self.rest.get_array_model_info(array)
        sl = (vol_header['serviceLevel'] if
              vol_header.get('serviceLevel') else 'None')
        wl = vol_header['workload'] if vol_header.get('workload') else 'None'
        cd = 'False' if vol_header.get('compressionEnabled') else 'True'

        metadata = {'DeviceID': device_id,
                    'DeviceLabel': vol_header['userDefinedIdentifier'],
                    'ArrayID': array, 'ArrayModel': array_model,
                    'ServiceLevel': sl, 'Workload': wl,
                    'Emulation': vol_header['emulationType'],
                    'Configuration': vol_header['configuration'],
                    'CompressionDisabled': cd}

        is_rep_enabled = vol_info['rdfInfo']['RDF']
        if is_rep_enabled:
            rdf_info = vol_info['rdfInfo']
            rdf_session = rdf_info['RDFSession'][0]
            rdf_num = rdf_session['SRDFGroupNumber']
            rdfg_info = self.rest.get_rdf_group(array, str(rdf_num))
            r2_array_model, __ = self.rest.get_array_model_info(
                rdf_session['remoteSymmetrixID'])

            metadata.update(
                {'ReplicationEnabled': 'True',
                 'R2-DeviceID': rdf_session['remoteDeviceID'],
                 'R2-ArrayID': rdf_session['remoteSymmetrixID'],
                 'R2-ArrayModel': r2_array_model,
                 'ReplicationMode': rdf_session['SRDFReplicationMode'],
                 'RDFG-Label': rdfg_info['label'],
                 'R1-RDFG': rdf_session['SRDFGroupNumber'],
                 'R2-RDFG': rdf_session['SRDFRemoteGroupNumber']})

            if metadata.get('ReplicationMode') == utils.RDF_ACTIVE.title():
                metadata['ReplicationMode'] = utils.REP_METRO
        else:
            metadata['ReplicationEnabled'] = 'False'

        return metadata

    def get_snapshot_metadata(self, array, device_id, snap_name):
        """Get snapshot metadata for model_update.

        :param array: the array ID
        :param device_id: the device ID
        :param snap_name: the snapshot name
        :returns: dict -- volume metadata
        """
        snap_id_list = list()
        snap_info = self.rest.get_volume_snap_info(array, device_id)
        device_name = snap_info.get('deviceName')
        snapshot_src_list = snap_info.get('snapshotSrcs')
        for snapshot_src in snapshot_src_list:
            if snap_name == snapshot_src.get('snapshotName'):
                snap_id_list.append(snapshot_src.get(
                    'snap_id') if self.rest.is_snap_id else snapshot_src.get(
                        'generation'))
        try:
            device_label = device_name.split(':')[1] if device_name else None
        except IndexError:
            device_label = None
        metadata = {'SnapshotLabel': snap_name,
                    'SourceDeviceID': device_id,
                    'SnapIdList': ', '.join(
                        six.text_type(v) for v in snap_id_list),
                    'is_snap_id': self.rest.is_snap_id}
        if device_label:
            metadata['SourceDeviceLabel'] = device_label
        return metadata

    def _check_and_add_tags_to_storage_array(
            self, serial_number, array_tag_list, extra_specs):
        """Add tags to a storage group.

        :param serial_number: the array serial number
        :param array_tag_list: the array tag list
        :param extra_specs: the extra specifications
        """
        if array_tag_list:
            existing_array_tags = self.rest.get_array_tags(serial_number)

            new_tag_list = self.utils.get_new_tags(
                self.utils.convert_list_to_string(array_tag_list),
                self.utils.convert_list_to_string(existing_array_tags))
            if not new_tag_list:
                LOG.warning("No new tags to add. Existing tags "
                            "associated with %(array)s are "
                            "%(tags)s.",
                            {'array': serial_number,
                             'tags': existing_array_tags})
            else:
                self._validate_array_tag_list(new_tag_list)
                LOG.info("Adding the tags %(tag_list)s to %(array)s",
                         {'tag_list': new_tag_list,
                          'array': serial_number})
                try:
                    self.rest.add_storage_array_tags(
                        serial_number, new_tag_list, extra_specs)
                except Exception as ex:
                    LOG.warning("Unexpected error: %(ex)s. If you still "
                                "want to add tags to this storage array, "
                                "please do so on the Unisphere UI.",
                                {'ex': ex})

    def prepare_replication_details(self, extra_specs):
        """Prepare details required for initialising replication.

        :param extra_specs: extra sepcifications
        :returns: first volume in SG, replication extra specs, replication info
                  dict -- bool, dict, dict
        """
        rep_info_dict, rep_first_vol, rdfg_empty = dict(), True, True

        # Get volume type replication extra specs
        rep_extra_specs = self._get_replication_extra_specs(
            extra_specs, extra_specs[utils.REP_CONFIG])

        # Get the target SG name for the current volume create op
        sg_name = self.utils.derive_default_sg_from_extra_specs(
            extra_specs, rep_mode=extra_specs['rep_mode'])
        rep_extra_specs['sg_name'] = sg_name

        # Check if the RDFG has volume in it regardless of target SG state
        rdf_group_details = self.rest.get_rdf_group(
            extra_specs['array'], rep_extra_specs['rdf_group_no'])
        rdfg_device_count = rdf_group_details['numDevices']
        if rdfg_device_count > 0:
            rdfg_empty = False

        # Check if there are any volumes in the SG, will return 0 if the SG
        # does not exist
        if self.rest.get_num_vols_in_sg(extra_specs['array'], sg_name):
            # Volumes exist, not first volume in SG
            rep_first_vol = False

            # Get the list of the current devices in the SG, this will help
            # with determining the new device added because no device ID is
            # returned
            local_device_list = self.rest.get_volume_list(
                extra_specs['array'],
                {'storageGroupId': sg_name})

            # Set replication info that we will need for creating volume in
            # existing SG, these are not required for new SGs as the only
            # additional step required is to SRDF protect the SG
            rep_info_dict.update({
                'local_array': extra_specs['array'],
                'remote_array': rep_extra_specs['array'],
                'rdf_group_no': rep_extra_specs['rdf_group_no'],
                'rep_mode': extra_specs['rep_mode'],
                'sg_name': sg_name,
                'service_level': extra_specs['slo'],
                'initial_device_list': local_device_list,
                'sync_interval': rep_extra_specs['sync_interval'],
                'sync_retries': rep_extra_specs['sync_retries']})

        return rep_first_vol, rep_extra_specs, rep_info_dict, rdfg_empty

    def srdf_protect_storage_group(self, extra_specs, rep_extra_specs,
                                   volume_dict):
        """SRDF protect a storage group.

        :param extra_specs: source extra specs
        :param rep_extra_specs: replication extra specs
        :param volume_dict: volume details dict
        """
        self.rest.srdf_protect_storage_group(
            extra_specs['array'], rep_extra_specs['array'],
            rep_extra_specs['rdf_group_no'], extra_specs['rep_mode'],
            volume_dict['storage_group'], rep_extra_specs['slo'], extra_specs)

    def get_and_set_remote_device_uuid(
            self, extra_specs, rep_extra_specs, volume_dict):
        """Get a remote device id and set device UUID.

        :param extra_specs: source extra specs
        :param rep_extra_specs: replication extra specs
        :param volume_dict: volume details dict
        :returns: remote device ID -- str
        """

        rdf_pair = self.rest.get_rdf_pair_volume(
            extra_specs['array'], rep_extra_specs['rdf_group_no'],
            volume_dict['device_id'])

        self.rest.rename_volume(rep_extra_specs['array'],
                                rdf_pair['remoteVolumeName'],
                                volume_dict['device_uuid'])

        return rdf_pair['remoteVolumeName']

    def gather_replication_updates(self, extra_specs, rep_extra_specs,
                                   volume_dict):
        """Gather replication updates for returns.

        :param extra_specs: extra specs
        :param rep_extra_specs: replication extra specs
        :param volume_dict: volume info dict
        :returns: replication status, replication info -- str, dict
        """
        replication_update = (
            {'replication_status': REPLICATION_ENABLED,
             'replication_driver_data': six.text_type(
                 {'array': rep_extra_specs['array'],
                  'device_id': volume_dict['remote_device_id']})})

        rep_info_dict = self.volume_metadata.gather_replication_info(
            volume_dict['device_uuid'], 'replication', False,
            local_array=extra_specs['array'],
            remote_array=rep_extra_specs['array'],
            target_device_id=volume_dict['remote_device_id'],
            target_name=volume_dict['device_uuid'],
            rdf_group_no=rep_extra_specs['rdf_group_no'],
            rep_mode=extra_specs['rep_mode'],
            replication_status=REPLICATION_ENABLED,
            rdf_group_label=rep_extra_specs['rdf_group_label'],
            target_array_model=rep_extra_specs['target_array_model'],
            backend_id=rep_extra_specs[
                utils.REP_CONFIG].get(utils.BACKEND_ID, None))

        return replication_update, rep_info_dict

    def _cleanup_non_rdf_volume_create_post_failure(
            self, volume, volume_name, extra_specs, device_ids):
        """Delete lingering volumes that exist in an non-RDF SG post exception.

        :param volume: Cinder volume -- Volume
        :param volume_name: Volume name -- str
        :param extra_specs: Volume extra specs -- dict
        :param device_ids: Devices ids to be deleted -- list
        """
        array = extra_specs[utils.ARRAY]
        for device_id in device_ids:
            self.masking.remove_and_reset_members(
                array, volume, device_id, volume_name, extra_specs, False)
            self._delete_from_srp(
                array, device_id, volume_name, extra_specs)

    def _cleanup_rdf_volume_create_post_failure(
            self, volume, volume_name, extra_specs, device_ids):
        """Delete lingering volumes that exist in an RDF SG post exception.

        :param volume: Cinder volume -- Volume
        :param volume_name: Volume name -- str
        :param extra_specs: Volume extra specs -- dict
        :param device_ids: Devices ids to be deleted -- list
        """
        __, rep_extra_specs, __, __ = self.prepare_replication_details(
            extra_specs)
        array = extra_specs[utils.ARRAY]
        srp = extra_specs['srp']
        slo = extra_specs['slo']
        workload = extra_specs['workload']
        do_disable_compression = self.utils.is_compression_disabled(
            extra_specs)
        rep_mode = extra_specs['rep_mode']
        rdf_group = rep_extra_specs['rdf_group_no']
        rep_config = extra_specs[utils.REP_CONFIG]

        if rep_mode is utils.REP_SYNC:
            storagegroup_name = self.utils.get_default_storage_group_name(
                srp, slo, workload, do_disable_compression, True, rep_mode)
        else:
            storagegroup_name = self.utils.get_rdf_management_group_name(
                rep_config)

        self.rest.srdf_resume_replication(
            array, storagegroup_name, rdf_group, rep_extra_specs)
        for device_id in device_ids:
            __, __, vol_is_rdf = self.rest.is_vol_in_rep_session(
                array, device_id)
            if vol_is_rdf:
                self.cleanup_rdf_device_pair(array, rdf_group, device_id,
                                             extra_specs)
            else:
                self.masking.remove_and_reset_members(
                    array, volume, device_id, volume_name, extra_specs, False)
                self._delete_from_srp(
                    array, device_id, volume_name, extra_specs)

    def _validate_rdfg_status(self, array, extra_specs):
        """Validate RDF group states before and after various operations

        :param array: array serial number -- str
        :param extra_specs: volume extra specs -- dict
        """
        rep_extra_specs = self._get_replication_extra_specs(
            extra_specs, extra_specs[utils.REP_CONFIG])
        rep_mode = extra_specs['rep_mode']
        rdf_group_no = rep_extra_specs['rdf_group_no']

        # Get default storage group for volume
        disable_compression = self.utils.is_compression_disabled(extra_specs)
        storage_group_name = self.utils.get_default_storage_group_name(
            extra_specs['srp'], extra_specs['slo'], extra_specs['workload'],
            disable_compression, True, extra_specs['rep_mode'])

        # Check for storage group. Will be unavailable for first vol create
        storage_group_details = self.rest.get_storage_group(
            array, storage_group_name)
        storage_group_available = storage_group_details is not None

        if storage_group_available:
            is_rep = self._validate_storage_group_is_replication_enabled(
                array, storage_group_name)
            is_exclusive = self._validate_rdf_group_storage_group_exclusivity(
                array, storage_group_name)
            is_valid_states = self._validate_storage_group_rdf_states(
                array, storage_group_name, rdf_group_no, rep_mode)
            if not (is_rep and is_exclusive and is_valid_states):
                msg = (_('RDF validation for storage group %s failed. Please '
                         'see logged error messages for specific details.'
                         ) % storage_group_name)
                raise exception.VolumeBackendAPIException(msg)

        # Perform checks against Async or Metro management storage groups
        if rep_mode is not utils.REP_SYNC:
            management_sg_name = self.utils.get_rdf_management_group_name(
                extra_specs['rep_config'])
            management_sg_details = self.rest.get_storage_group(
                array, management_sg_name)
            management_sg_available = management_sg_details is not None

            if management_sg_available:
                is_rep = self._validate_storage_group_is_replication_enabled(
                    array, management_sg_name)
                is_excl = self._validate_rdf_group_storage_group_exclusivity(
                    array, management_sg_name)
                is_valid_states = self._validate_storage_group_rdf_states(
                    array, management_sg_name, rdf_group_no, rep_mode)
                is_cons = self._validate_management_group_volume_consistency(
                    array, management_sg_name, rdf_group_no)
                if not (is_rep and is_excl and is_valid_states and is_cons):
                    msg = (_(
                        'RDF validation for storage group %s failed. Please '
                        'see logged error messages for specific details.')
                        % management_sg_name)
                    raise exception.VolumeBackendAPIException(msg)

        # Perform check to make sure we have the same number of devices
        remote_array = rep_extra_specs[utils.ARRAY]
        rdf_group = self.rest.get_rdf_group(
            array, rdf_group_no)
        remote_rdf_group_no = rdf_group.get('remoteRdfgNumber')
        remote_rdf_group = self.rest.get_rdf_group(
            remote_array, remote_rdf_group_no)
        local_rdfg_device_count = rdf_group.get('numDevices')
        remote_rdfg_device_count = remote_rdf_group.get('numDevices')
        if local_rdfg_device_count != remote_rdfg_device_count:
            msg = (_(
                'RDF validation failed. Different device counts found for '
                'local and remote RDFGs. Local RDFG %s has %s devices. Remote '
                'RDFG %s has %s devices. The same number of devices is '
                'expected. Check RDFGs for broken RDF pairs and cleanup or '
                'recreate the pairs as needed.') % (
                rdf_group_no, local_rdfg_device_count, remote_rdf_group_no,
                remote_rdfg_device_count))
            raise exception.VolumeDriverException(msg)

    def _validate_storage_group_is_replication_enabled(
            self, array, storage_group_name):
        """Validate that a storage groups is marked as RDF enabled

        :param array: array serial number -- str
        :param storage_group_name: name of the storage group -- str
        :returns: consistency validation checks passed -- boolean
        """
        is_valid = True
        sg_details = self.rest.get_storage_group_rep(array, storage_group_name)
        sg_rdf_enabled = sg_details.get('rdf', False)
        if not sg_rdf_enabled:
            LOG.error('Storage group %s is expected to be RDF enabled but '
                      'is not. Please check that all volumes in this storage '
                      'group are RDF enabled and part of the same RDFG.',
                      storage_group_name)
            is_valid = False
        return is_valid

    def _validate_storage_group_rdf_states(
            self, array, storage_group_name, rdf_group_no, rep_mode):
        """Validate that the RDF states found for storage groups are valid.

        :param array: array serial number -- str
        :param storage_group_name: name of the storage group -- str
        :param rep_mode: replication mode being used -- str
        :returns: consistency validation checks passed -- boolean
        """
        is_valid = True
        sg_rdf_states = self.rest.get_storage_group_rdf_group_state(
            array, storage_group_name, rdf_group_no)
        # Verify Async & Metro modes only have a single state
        if rep_mode is not utils.REP_SYNC:
            if len(sg_rdf_states) > 1:
                sg_states_str = (', '.join(sg_rdf_states))
                LOG.error('More than one RDFG state found for storage group '
                          '%s. We expect a single state for all volumes when '
                          'using %s replication mode. Found %s states.',
                          storage_group_name, rep_mode, sg_states_str)
                is_valid = False

        # Determine which list of valid states to use
        if rep_mode is utils.REP_SYNC:
            valid_states = utils.RDF_VALID_STATES_SYNC
        elif rep_mode is utils.REP_ASYNC:
            valid_states = utils.RDF_VALID_STATES_ASYNC
        else:
            valid_states = utils.RDF_VALID_STATES_METRO

        # Validate storage group states
        for state in sg_rdf_states:
            if state.lower() not in valid_states:
                valid_states_str = (', '.join(valid_states))
                LOG.error('Invalid RDF state found for storage group %s. '
                          'Found state %s. Valid states are %s.',
                          storage_group_name, state, valid_states_str)
                is_valid = False
        return is_valid

    def _validate_rdf_group_storage_group_exclusivity(
            self, array, storage_group_name):
        """Validate that a storage group only has one RDF group.

        :param array: array serial number -- str
        :param storage_group_name: name of storage group -- str
        :returns: consistency validation checks passed -- boolean
        """
        is_valid = True
        sg_rdf_groups = self.rest.get_storage_group_rdf_groups(
            array, storage_group_name)
        if len(sg_rdf_groups) > 1:
            rdf_groups_str = ', '.join(sg_rdf_groups)
            LOG.error('Detected more than one RDF group associated with '
                      'storage group %s. Only one RDFG should be associated '
                      'with a storage group. Found RDF groups %s',
                      storage_group_name, rdf_groups_str)
            is_valid = False
        return is_valid

    def _validate_management_group_volume_consistency(
            self, array, management_sg_name, rdf_group_number):
        """Validate volume consistency between management SG and RDF group

        :param array: array serial number -- str
        :param management_sg_name: name of storage group -- str
        :param rdf_group_number: rdf group number to check -- str
        :returns: consistency validation checks passed -- boolean
        """
        is_valid = True
        rdfg_volumes = self.rest.get_rdf_group_volume_list(
            array, rdf_group_number)
        sg_volumes = self.rest.get_volumes_in_storage_group(
            array, management_sg_name)
        missing_volumes = list()
        for rdfg_volume in rdfg_volumes:
            if rdfg_volume not in sg_volumes:
                missing_volumes.append(rdfg_volume)
        if missing_volumes:
            missing_volumes_str = ', '.join(missing_volumes)
            LOG.error(
                'Inconsistency found between management group %s and RDF '
                'group %s. The following volumes are not in the management '
                'storage group %s. All Asynchronous and Metro volumes must '
                'be managed together in their respective management storage '
                'groups.',
                management_sg_name, rdf_group_number, missing_volumes_str)
            is_valid = False
        return is_valid
