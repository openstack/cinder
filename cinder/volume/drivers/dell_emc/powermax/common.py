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

import ast
from copy import deepcopy
import math
import random
import sys
import time

from oslo_config import cfg
from oslo_config import types
from oslo_log import log as logging
from oslo_utils import strutils
import six

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder.volume import configuration
from cinder.volume.drivers.dell_emc.powermax import masking
from cinder.volume.drivers.dell_emc.powermax import metadata as volume_metadata
from cinder.volume.drivers.dell_emc.powermax import migrate
from cinder.volume.drivers.dell_emc.powermax import provision
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume.drivers.dell_emc.powermax import utils
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types
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


powermax_opts = [
    cfg.IntOpt('interval',
               default=3,
               help='Use this value to specify '
                    'length of the interval in seconds.'),
    cfg.IntOpt('retries',
               default=200,
               help='Use this value to specify '
                    'number of retries.'),
    cfg.IntOpt(utils.VMAX_SNAPVX_UNLINK_LIMIT,
               default=3,
               help='DEPRECATED: vmax_snapvc_unlink_limit.',
               deprecated_for_removal=True,
               deprecated_reason='Replaced by powermax_snapvx_unlink_limit.'),
    cfg.BoolOpt('initiator_check',
                default=False,
                help='Use this value to enable '
                     'the initiator_check.'),
    cfg.PortOpt(utils.VMAX_SERVER_PORT_OLD,
                deprecated_for_removal=True,
                deprecated_since="13.0.0",
                deprecated_reason='Unisphere port should now be '
                                  'set using the common san_api_port '
                                  'config option instead.',
                default=8443,
                help='REST server port number.'),
    cfg.StrOpt(utils.VMAX_ARRAY,
               help='DEPRECATED: vmax_array.',
               deprecated_for_removal=True,
               deprecated_reason='Replaced by powermax_array.'),
    cfg.StrOpt(utils.VMAX_SRP,
               help='DEPRECATED: vmax_srp.',
               deprecated_for_removal=True,
               deprecated_reason='Replaced by powermax_srp.'),
    cfg.StrOpt(utils.VMAX_SERVICE_LEVEL,
               help='DEPRECATED: vmax_service_level.',
               deprecated_for_removal=True,
               deprecated_reason='Replaced by powermax_service_level.'),
    cfg.StrOpt(utils.VMAX_WORKLOAD,
               help='Workload, setting this as an extra spec in '
                    'pool_name is preferable.'),
    cfg.ListOpt(utils.VMAX_PORT_GROUPS,
                bounds=True,
                help='DEPRECATED: vmax_port_groups.',
                deprecated_for_removal=True,
                deprecated_reason='Replaced by powermax_port_groups.'),
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
    cfg.IntOpt(utils.POWERMAX_SNAPVX_UNLINK_LIMIT,
               default=3,
               help='Use this value to specify '
                    'the maximum number of unlinks '
                    'for the temporary snapshots '
                    'before a clone operation.'),
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
                     'configured prior for server connection.')]


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

        self.protocol = prtcl
        self.configuration = configuration
        self.configuration.append_config_values(powermax_opts)
        self.rest = rest.PowerMaxRest()
        self.utils = utils.PowerMaxUtils()
        self.masking = masking.PowerMaxMasking(prtcl, self.rest)
        self.provision = provision.PowerMaxProvision(self.rest)
        self.version = version
        self.volume_metadata = volume_metadata.PowerMaxVolumeMetadata(
            self.rest, version, LOG.isEnabledFor(logging.DEBUG))
        self.migrate = migrate.PowerMaxMigrate(prtcl, self.rest)

        # replication
        self.replication_enabled = False
        self.extend_replicated_vol = False
        self.rep_devices = None
        self.active_backend_id = active_backend_id
        self.failover = False
        self._get_replication_info()
        self._get_u4p_failover_info()
        self.next_gen = False
        self._gather_info()
        self.version_dict = {}

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
            self.array_model, self.next_gen = self.rest.get_array_model_info(
                array_info['SerialNumber'])
        finalarrayinfolist = self._get_slo_workload_combinations(
            array_info)
        self.pool_info['arrays_info'] = finalarrayinfolist

    def _get_attributes_from_config(self):
        """Get relevent details from configuration file."""
        self.interval = self.configuration.safe_get('interval')
        self.retries = self.configuration.safe_get('retries')
        self.snapvx_unlink_limit = self._get_unlink_configuration_value(
            utils.VMAX_SNAPVX_UNLINK_LIMIT,
            utils.POWERMAX_SNAPVX_UNLINK_LIMIT)
        self.pool_info['backend_name'] = (
            self.configuration.safe_get('volume_backend_name'))
        mosr = volume_utils.get_max_over_subscription_ratio(
            self.configuration.safe_get('max_over_subscription_ratio'), True)
        self.pool_info['max_over_subscription_ratio'] = mosr
        self.pool_info['reserved_percentage'] = (
            self.configuration.safe_get('reserved_percentage'))
        LOG.debug(
            "Updating volume stats on file %(emcConfigFileName)s on "
            "backend %(backendName)s.",
            {'emcConfigFileName': self.pool_info['config_file'],
             'backendName': self.pool_info['backend_name']})

    def _get_u4p_failover_info(self):
        """Gather Unisphere failover target information, if provided."""

        key_dict = {'san_ip': 'RestServerIp',
                    'san_api_port': 'RestServerPort',
                    'san_login': 'RestUserName',
                    'san_password': 'RestPassword',
                    'driver_ssl_cert_verify': 'SSLVerify',
                    'driver_ssl_cert_path': 'SSLPath'}

        if self.configuration.safe_get('u4p_failover_target'):
            u4p_targets = self.configuration.safe_get('u4p_failover_target')
            formatted_target_list = list()
            for target in u4p_targets:
                formatted_target = {key_dict[key]: value for key, value in
                                    target.items()}

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
        self.rep_config = None
        self.replication_targets = None
        if hasattr(self.configuration, 'replication_device'):
            self.rep_devices = self.configuration.safe_get(
                'replication_device')
        if self.rep_devices and len(self.rep_devices) == 1:
            self.rep_config = self.utils.get_replication_config(
                self.rep_devices)
            if self.rep_config:
                self.replication_targets = [self.rep_config['array']]
                if self.active_backend_id == self.rep_config['array']:
                    self.failover = True
                self.extend_replicated_vol = self.rep_config['allow_extend']
                self.allow_delete_metro = (
                    self.rep_config['allow_delete_metro']
                    if self.rep_config.get('allow_delete_metro') else False)
                # use self.replication_enabled for update_volume_stats
                self.replication_enabled = True
                LOG.debug("The replication configuration is %(rep_config)s.",
                          {'rep_config': self.rep_config})
        elif self.rep_devices and len(self.rep_devices) > 1:
            LOG.error("More than one replication target is configured. "
                      "Dell EMC PowerMax/VMAX only suppports a single "
                      "replication target. Replication will not be enabled.")

    def _get_slo_workload_combinations(self, array_info):
        """Method to query the array for SLO and Workloads.

        Takes the arrayinfolist object and generates a set which has
        all available SLO & Workload combinations
        :param array_info: the array information
        :returns: finalarrayinfolist
        :raises: VolumeBackendAPIException:
        """
        try:
            array = array_info['SerialNumber']
            if self.failover:
                array = self.active_backend_id

            slo_settings = self.rest.get_slo_list(
                array, self.next_gen, self.array_model)
            slo_list = [x for x in slo_settings
                        if x.lower() not in ['none', 'optimized']]
            workload_settings = self.rest.get_workload_settings(
                array, self.next_gen)
            workload_settings.append('None')
            slo_workload_set = set(
                ['%(slo)s:%(workload)s' % {'slo': slo,
                                           'workload': workload}
                 for slo in slo_list for workload in workload_settings])
            slo_workload_set.add('None:None')

            if self.next_gen:
                LOG.warning("Workloads have been deprecated for arrays "
                            "running PowerMax OS uCode level 5978 or higher. "
                            "Any supplied workloads will be treated as None "
                            "values. It is highly recommended to create a new "
                            "volume type without a workload specified.")
                for slo in slo_list:
                    slo_workload_set.add(slo)
                slo_workload_set.add('None')
                slo_workload_set.add('Optimized')
                slo_workload_set.add('Optimized:None')
                # If array is 5978 or greater and a VMAX AFA add legacy SL/WL
                # combinations
                if any(self.array_model in x for x in
                       utils.VMAX_AFA_MODELS):
                    slo_workload_set.add('Diamond:OLTP')
                    slo_workload_set.add('Diamond:OLTP_REP')
                    slo_workload_set.add('Diamond:DSS')
                    slo_workload_set.add('Diamond:DSS_REP')
                    slo_workload_set.add('Diamond:None')

            if not any(self.array_model in x for x in
                       utils.VMAX_AFA_MODELS):
                slo_workload_set.add('Optimized:None')

            finalarrayinfolist = []
            for sloWorkload in slo_workload_set:
                temparray_info = array_info.copy()
                try:
                    slo, workload = sloWorkload.split(':')
                    temparray_info['SLO'] = slo
                    temparray_info['Workload'] = workload
                except ValueError:
                    temparray_info['SLO'] = sloWorkload
                finalarrayinfolist.append(temparray_info)
        except Exception as e:
            exception_message = (_(
                "Unable to get the SLO/Workload combinations from the array. "
                "Exception received was %(e)s") % {'e': six.text_type(e)})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        return finalarrayinfolist

    def create_volume(self, volume):
        """Creates a EMC(PowerMax/VMAX) volume from a storage group.

        :param volume: volume object
        :returns:  model_update - dict
        """
        model_update = {}
        rep_info_dict = {}
        rep_driver_data = {}
        volume_id = volume.id
        group_name = None
        group_id = None
        extra_specs = self._initial_setup(volume)
        # Check if the RDF group is valid
        if self.utils.is_replication_enabled(extra_specs):
            self.get_rdf_details(extra_specs[utils.ARRAY])

        if 'qos' in extra_specs:
            del extra_specs['qos']

        # Volume_name naming convention is 'OS-UUID'.
        volume_name = self.utils.get_volume_element_name(volume_id)
        volume_size = volume.size

        volume_dict = (self._create_volume(
            volume_name, volume_size, extra_specs))

        # Set-up volume replication, if enabled
        if self.utils.is_replication_enabled(extra_specs):
            rep_update, rep_info_dict = self._replicate_volume(
                volume, volume_name, volume_dict, extra_specs)
            rep_driver_data = rep_update['replication_driver_data']
            model_update.update(rep_update)

        # Add volume to group, if required
        if volume.group_id is not None:
            if (volume_utils.is_group_a_cg_snapshot_type(volume.group)
                    or volume.group.is_replicated):
                group_id = volume.group_id
                group_name = self._add_new_volume_to_volume_group(
                    volume, volume_dict['device_id'], volume_name,
                    extra_specs, rep_driver_data)
        model_update.update(
            {'provider_location': six.text_type(volume_dict)})

        self.volume_metadata.capture_create_volume(
            volume_dict['device_id'], volume, group_name, group_id,
            extra_specs, rep_info_dict, 'create')

        LOG.info("Leaving create_volume: %(name)s. Volume dict: %(dict)s.",
                 {'name': volume_name, 'dict': volume_dict})

        return model_update

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

        clone_dict = self._create_cloned_volume(
            volume, snapshot, extra_specs, is_snapshot=False,
            from_snapvx=from_snapvx)

        # Set-up volume replication, if enabled
        if self.utils.is_replication_enabled(extra_specs):
            rep_update, rep_info_dict = (
                self._replicate_volume(
                    volume, snapshot['name'], clone_dict, extra_specs))
            model_update.update(rep_update)

        model_update.update(
            {'provider_location': six.text_type(clone_dict)})

        self.volume_metadata.capture_create_volume(
            clone_dict['device_id'], volume, None, None,
            extra_specs, rep_info_dict, 'createFromSnapshot',
            source_snapshot_id=snapshot.id)

        return model_update

    def create_cloned_volume(self, clone_volume, source_volume):
        """Creates a clone of the specified volume.

        :param clone_volume: clone volume Object
        :param source_volume: volume object
        :returns: model_update, dict
        """
        model_update, rep_info_dict = {}, {}
        extra_specs = self._initial_setup(clone_volume)
        clone_dict = self._create_cloned_volume(clone_volume, source_volume,
                                                extra_specs)

        # Set-up volume replication, if enabled
        if self.utils.is_replication_enabled(extra_specs):
            rep_update, rep_info_dict = self._replicate_volume(
                clone_volume, clone_volume.name, clone_dict, extra_specs)
            model_update.update(rep_update)

        model_update.update(
            {'provider_location': six.text_type(clone_dict)})
        self.volume_metadata.capture_create_volume(
            clone_dict['device_id'], clone_volume, None, None,
            extra_specs, rep_info_dict, 'createFromVolume',
            temporary_snapvx=clone_dict.get('snap_name'),
            source_device_id=clone_dict.get('source_device_id'))
        return model_update

    def _replicate_volume(self, volume, volume_name, volume_dict, extra_specs,
                          delete_src=True):
        """Setup up remote replication for a volume.

        :param volume: the volume object
        :param volume_name: the volume name
        :param volume_dict: the volume dict
        :param extra_specs: the extra specifications
        :param delete_src: flag to indicate if source should be deleted on
                           if replication fails
        :returns: replication model_update, rep_info_dict
        """
        array = volume_dict['array']
        try:
            device_id = volume_dict['device_id']
            replication_status, replication_driver_data, rep_info_dict = (
                self.setup_volume_replication(
                    array, volume, device_id, extra_specs))
        except Exception:
            if delete_src:
                self._cleanup_replication_source(
                    array, volume, volume_name, volume_dict, extra_specs)
            raise
        return ({'replication_status': replication_status,
                 'replication_driver_data': six.text_type(
                     replication_driver_data)}, rep_info_dict)

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
        snapshot_dict = self._create_cloned_volume(
            snapshot, volume, extra_specs, is_snapshot=True)
        self.volume_metadata.capture_snapshot_info(
            volume, extra_specs, 'createSnapshot', snapshot_dict['snap_name'])
        model_update = {'provider_location': six.text_type(snapshot_dict)}
        return model_update

    def delete_snapshot(self, snapshot, volume):
        """Deletes a snapshot.

        :param snapshot: snapshot object
        :param volume: source volume
        """
        LOG.info("Delete Snapshot: %(snapshotName)s.",
                 {'snapshotName': snapshot.name})
        extra_specs = self._initial_setup(volume)
        sourcedevice_id, snap_name = self._parse_snap_info(
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
            self.provision.delete_volume_snap_check_for_links(
                extra_specs[utils.ARRAY], snap_name,
                sourcedevice_id, extra_specs)

            LOG.info("Leaving delete_snapshot: %(ssname)s.",
                     {'ssname': snap_name})
        self.volume_metadata.capture_snapshot_info(
            volume, extra_specs, 'deleteSnapshot', None)

    def _remove_members(self, array, volume, device_id,
                        extra_specs, connector, is_multiattach,
                        async_grp=None):
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
            extra_specs, reset, connector, async_grp=async_grp)
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
        if 'qos' in extra_specs:
            del extra_specs['qos']
        rep_extra_specs = self._get_replication_extra_specs(
            extra_specs, self.rep_config)
        if self.utils.is_volume_failed_over(volume):
            extra_specs = rep_extra_specs
        volume_name = volume.name
        async_grp = None
        LOG.info("Unmap volume: %(volume)s.", {'volume': volume})
        if connector is not None:
            host = self.utils.get_host_short_name(connector['host'])
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
                current_host_occurances = host_list.count(host)
                if current_host_occurances > 1:
                    LOG.info("Volume is attached to multiple instances on "
                             "this host. Not removing the volume from the "
                             "masking view.")
                    return
        else:
            LOG.warning("Cannot get host name from connector object - "
                        "assuming force-detach.")
            host = None

        device_info, is_multiattach = (
            self.find_host_lun_id(volume, host, extra_specs))
        if 'hostlunid' not in device_info:
            LOG.info("Volume %s is not mapped. No volume to unmap.",
                     volume_name)
            return
        array = extra_specs[utils.ARRAY]
        if self.utils.does_vol_need_rdf_management_group(extra_specs):
            async_grp = self.utils.get_async_rdf_managed_grp_name(
                self.rep_config)
        self._remove_members(array, volume, device_info['device_id'],
                             extra_specs, connector, is_multiattach,
                             async_grp=async_grp)
        if self.utils.is_metro_device(self.rep_config, extra_specs):
            # Need to remove from remote masking view
            device_info, __ = (self.find_host_lun_id(
                volume, host, extra_specs, rep_extra_specs))
            if 'hostlunid' in device_info:
                self._remove_members(
                    rep_extra_specs[utils.ARRAY], volume,
                    device_info['device_id'], rep_extra_specs, connector,
                    is_multiattach, async_grp=async_grp)
            else:
                # Make an attempt to clean up initiator group
                self.masking.attempt_ig_cleanup(
                    connector, self.protocol, rep_extra_specs[utils.ARRAY],
                    True)
        if is_multiattach and LOG.isEnabledFor(logging.DEBUG):
            mv_list, sg_list = (
                self._get_mvs_and_sgs_from_volume(
                    extra_specs[utils.ARRAY],
                    device_info['device_id']))
        self.volume_metadata.capture_detach_info(
            volume, extra_specs, device_info['device_id'], mv_list,
            sg_list)

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
        extra_specs = self._initial_setup(volume)
        is_multipath = connector.get('multipath', False)
        rep_extra_specs = self._get_replication_extra_specs(
            extra_specs, self.rep_config)
        remote_port_group = None
        volume_name = volume.name
        LOG.info("Initialize connection: %(volume)s.",
                 {'volume': volume_name})
        if (self.utils.is_metro_device(self.rep_config, extra_specs)
                and not is_multipath and self.protocol.lower() == 'iscsi'):
            LOG.warning("Multipathing is not correctly enabled "
                        "on your system.")
            return

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
                     {'volume': volume_name, 'host': connector['host'],
                      'hostlunid': hostlunid})
            port_group_name = (
                self.get_port_group_from_masking_view(
                    extra_specs[utils.ARRAY],
                    device_info_dict['maskingview']))
            if self.utils.is_metro_device(self.rep_config, extra_specs):
                remote_info_dict, is_multiattach = (
                    self.find_host_lun_id(volume, connector['host'],
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
            if self.utils.is_metro_device(self.rep_config, extra_specs):
                # Need to attach on remote side
                metro_host_lun, remote_port_group = self._attach_metro_volume(
                    volume, connector, is_multiattach, extra_specs,
                    rep_extra_specs)
                device_info_dict['metro_hostlunid'] = metro_host_lun
        if self.protocol.lower() == 'iscsi':
            device_info_dict['ip_and_iqn'] = (
                self._find_ip_and_iqns(
                    extra_specs[utils.ARRAY], port_group_name))
            if self.utils.is_metro_device(self.rep_config, extra_specs):
                device_info_dict['metro_ip_and_iqn'] = (
                    self._find_ip_and_iqns(
                        rep_extra_specs[utils.ARRAY], remote_port_group))
            device_info_dict['is_multipath'] = is_multipath

        if is_multiattach and LOG.isEnabledFor(logging.DEBUG):
            masking_view_dict['mv_list'], masking_view_dict['sg_list'] = (
                self._get_mvs_and_sgs_from_volume(
                    extra_specs[utils.ARRAY],
                    masking_view_dict[utils.DEVICE_ID]))

        self.volume_metadata.capture_attach_info(
            volume, extra_specs, masking_view_dict, connector['host'],
            is_multipath, is_multiattach)

        return device_info_dict

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
        :return: hostlunid, remote_port_group
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
            volume, connector['host'], extra_specs, rep_extra_specs)
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
        self._unmap_lun(volume, connector)

    def extend_volume(self, volume, new_size):
        """Extends an existing volume.

        :param volume: the volume Object
        :param new_size: the new size to increase the volume to
        :returns: dict -- modifiedVolumeDict - the extended volume Object
        :raises: VolumeBackendAPIException:
        """
        original_vol_size = volume.size
        volume_name = volume.name
        extra_specs = self._initial_setup(volume)
        array = extra_specs[utils.ARRAY]
        device_id = self._find_device_on_array(volume, extra_specs)
        if device_id is None:
            exception_message = (_("Cannot find Volume: %(volume_name)s. "
                                   "Extend operation.  Exiting....")
                                 % {'volume_name': volume_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        # Check if volume is part of an on-going clone operation
        self._sync_check(array, device_id, extra_specs)
        __, snapvx_src, __ = self.rest.is_vol_in_rep_session(array, device_id)
        if snapvx_src:
            if not self.rest.is_next_gen_array(array):
                exception_message = (
                    _("The volume: %(volume)s is a snapshot source. "
                      "Extending a volume with snapVx snapshots is only "
                      "supported on PowerMax/VMAX from HyperMaxOS version "
                      "5978 onwards. Exiting...") % {'volume': volume_name})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    message=exception_message)

        if int(original_vol_size) > int(new_size):
            exception_message = (_(
                "Your original size: %(original_vol_size)s GB is greater "
                "than: %(new_size)s GB. Only Extend is supported. Exiting...")
                % {'original_vol_size': original_vol_size,
                   'new_size': new_size})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        LOG.info("Extending volume %(volume)s to %(new_size)d GBs",
                 {'volume': volume_name,
                  'new_size': int(new_size)})
        if self.utils.is_replication_enabled(extra_specs):
            # Extra logic required if volume is replicated
            self.extend_volume_is_replicated(
                array, volume, device_id, volume_name, new_size, extra_specs)
        else:
            self.provision.extend_volume(
                array, device_id, new_size, extra_specs)

        self.volume_metadata.capture_extend_info(
            volume, new_size, device_id, extra_specs, array)

        LOG.debug("Leaving extend_volume: %(volume_name)s. ",
                  {'volume_name': volume_name})

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
                array_info = self.get_secondary_stats_info(
                    self.rep_config, array_info)
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
                if self.rep_config and self.rep_config.get('mode'):
                    extra_specs[utils.REP_MODE] = self.rep_config['mode']
                if self.rep_config and self.rep_config.get(utils.METROBIAS):
                    extra_specs[utils.METROBIAS] = self.rep_config[
                        utils.METROBIAS]
        return extra_specs, qos_specs

    def _find_device_on_array(self, volume, extra_specs):
        """Given the volume get the PowerMax/VMAX device Id.

        :param volume: volume object
        :param extra_specs: the extra Specs
        :returns: array, device_id
        """
        founddevice_id = None
        volume_name = volume.id
        try:
            name_id = volume._name_id
        except AttributeError:
            name_id = None
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
            device_id = self.get_remote_target_device(
                extra_specs[utils.ARRAY], volume, device_id)[0]
            extra_specs = rep_extra_specs
        host_name = self.utils.get_host_short_name(host) if host else None
        if device_id:
            array = extra_specs[utils.ARRAY]
            # Return only masking views for this host
            host_maskingviews, all_masking_view_list = (
                self._get_masking_views_from_volume(
                    array, device_id, host_name))

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
                              "than %(host)s - multiattach case.",
                              {'host': host})
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
        :return: masking view list, is metro
        """
        is_metro = False
        extra_specs = self._initial_setup(volume)
        mv_list, __ = self._get_masking_views_from_volume(array, device_id,
                                                          host)
        if self.utils.is_metro_device(self.rep_config, extra_specs):
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
        host_maskingview_list, all_masking_view_list = [], []
        host_compare = True if host else False
        mvs, __ = self._get_mvs_and_sgs_from_volume(array, device_id)
        for mv in mvs:
            all_masking_view_list.append(mv)
            if host_compare:
                if host.lower() in mv.lower():
                    host_maskingview_list.append(mv)
        maskingview_list = (host_maskingview_list if host_compare else
                            all_masking_view_list)
        return maskingview_list, all_masking_view_list

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

    def _initial_setup(self, volume, volume_type_id=None):
        """Necessary setup to accumulate the relevant information.

        The volume object has a host in which we can parse the
        config group name. The config group name is the key to our EMC
        configuration file. The emc configuration file contains srp name
        and array name which are mandatory fields.
        :param volume: the volume object
        :param volume_type_id: optional override of volume.volume_type_id
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

            extra_specs = self._set_vmax_extra_specs(extra_specs, array_info)
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
            device_id = self.get_remote_target_device(
                extra_specs[utils.ARRAY], volume, device_id)[0]
            extra_specs = rep_extra_specs
        if not device_id:
            exception_message = (_("Cannot retrieve volume %(vol)s "
                                   "from the array. ") % {'vol': volume_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(exception_message)

        protocol = self.utils.get_short_protocol_type(self.protocol)
        short_host_name = self.utils.get_host_short_name(connector['host'])
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
        masking_view_dict[utils.PORTGROUPNAME] = (
            extra_specs[utils.PORTGROUPNAME])
        masking_view_dict[utils.INITIATOR_CHECK] = (
            self._get_initiator_check_flag())

        child_sg_name, do_disable_compression, rep_enabled, short_pg_name = (
            self.utils.get_child_sg_name(short_host_name, extra_specs))
        masking_view_dict[utils.DISABLECOMPRESSION] = do_disable_compression
        masking_view_dict[utils.IS_RE] = rep_enabled
        mv_prefix = (
            "OS-%(shortHostName)s-%(protocol)s-%(pg)s"
            % {'shortHostName': short_host_name,
               'protocol': protocol, 'pg': short_pg_name})

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
        LOG.info("Create a replica from Volume: Clone Volume: %(clone_name)s "
                 "from Source Volume: %(source_name)s.",
                 {'clone_name': clone_name,
                  'source_name': source_volume.name})

        array = extra_specs[utils.ARRAY]
        is_clone_license = self.rest.is_snapvx_licensed(array)
        if from_snapvx:
            source_device_id, snap_name = self._parse_snap_info(
                array, source_volume)
        else:
            source_device_id = self._find_device_on_array(
                source_volume, extra_specs)

        if not is_clone_license:
            exception_message = (_(
                "SnapVx feature is not licensed on %(array)s.")
                % {'array': array})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        # Perform any snapvx cleanup if required before creating the clone
        self._clone_check(array, source_device_id, extra_specs)

        if not is_snapshot:
            clone_dict = self._create_replica(
                array, volume, source_device_id, extra_specs,
                snap_name=snap_name)
        else:
            clone_dict = self._create_snapshot(
                array, volume, source_device_id, extra_specs)

        LOG.debug("Leaving _create_cloned_volume: Volume: "
                  "%(clone_name)s Source Device Id: %(source_name)s ",
                  {'clone_name': clone_name,
                   'source_name': source_device_id})

        return clone_dict

    def _parse_snap_info(self, array, snapshot):
        """Given a snapshot object, parse the provider_location.

        :param array: the array serial number
        :param snapshot: the snapshot object
        :returns: sourcedevice_id, foundsnap_name
        """
        foundsnap_name = None
        sourcedevice_id = None
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
                return None, None
            # Ensure snapvx is on the array.
            try:
                snap_details = self.rest.get_volume_snap(
                    array, sourcedevice_id, snap_name)
                if snap_details:
                    foundsnap_name = snap_name
            except Exception as e:
                LOG.info("Exception in retrieving snapshot: %(e)s.",
                         {'e': e})
                foundsnap_name = None

        if foundsnap_name is None or sourcedevice_id is None:
            exception_message = (_("Error retrieving snapshot details. "
                                   "Snapshot name: %(snap)s") %
                                 {'snap': volume_name})
            LOG.error(exception_message)

        else:
            LOG.debug("Source volume: %(volume_name)s  Snap name: "
                      "%(foundsnap_name)s.",
                      {'volume_name': sourcedevice_id,
                       'foundsnap_name': foundsnap_name})

        return sourcedevice_id, foundsnap_name

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
        source_device_id = None
        volume_name = volume.name
        extra_specs = self._initial_setup(volume)
        prov_loc = volume.provider_location

        if isinstance(prov_loc, six.string_types):
            name = ast.literal_eval(prov_loc)
            source_device_id = name.get('source_device_id')

        device_id = self._find_device_on_array(volume, extra_specs)
        if device_id is None:
            LOG.error("Volume %(name)s not found on the array. "
                      "No volume to delete.",
                      {'name': volume_name})
            return volume_name

        array = extra_specs[utils.ARRAY]
        # Check if the volume being deleted is a
        # source or target for copy session
        self._sync_check(array, device_id, extra_specs,
                         source_device_id=source_device_id)
        # Remove from any storage groups and cleanup replication
        self._remove_vol_and_cleanup_replication(
            array, device_id, volume_name, extra_specs, volume)
        self._delete_from_srp(
            array, device_id, volume_name, extra_specs)
        return volume_name

    def _create_volume(
            self, volume_name, volume_size, extra_specs, in_use=False):
        """Create a volume.

        :param volume_name: the volume name
        :param volume_size: the volume size
        :param extra_specs: extra specifications
        :param in_use: if the volume is in 'in-use' state
        :return: volume_dict --dict
        :raises: VolumeBackendAPIException:
        """
        array = extra_specs[utils.ARRAY]
        array_model, next_gen = self.rest.get_array_model_info(array)
        if next_gen:
            extra_specs[utils.WORKLOAD] = 'NONE'
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

        # If the volume is in-use, set replication config for correct SG
        # creation
        if in_use and self.utils.is_replication_enabled(extra_specs):
            is_re, rep_mode = True, extra_specs['rep_mode']
        else:
            is_re, rep_mode = False, None

        storagegroup_name = self.masking.get_or_create_default_storage_group(
            array, extra_specs[utils.SRP], extra_specs[utils.SLO],
            extra_specs[utils.WORKLOAD], extra_specs,
            do_disable_compression, is_re, rep_mode)
        try:
            volume_dict = self.provision.create_volume_from_sg(
                array, volume_name, storagegroup_name,
                volume_size, extra_specs)
        except Exception:
            # if the volume create fails, check if the
            # storage group needs to be cleaned up
            LOG.error("Create volume failed. Checking if "
                      "storage group cleanup necessary...")
            num_vol_in_sg = self.rest.get_num_vols_in_sg(
                array, storagegroup_name)

            if num_vol_in_sg == 0:
                LOG.debug("There are no volumes in the storage group "
                          "%(sg_id)s. Deleting storage group.",
                          {'sg_id': storagegroup_name})
                self.rest.delete_storage_group(
                    array, storagegroup_name)
            raise

        return volume_dict

    def _set_vmax_extra_specs(self, extra_specs, pool_record):
        """Set the PowerMax/VMAX extra specs.

        The pool_name extra spec must be set, otherwise a default slo/workload
        will be chosen. The portgroup can either be passed as an extra spec
        on the volume type (e.g. 'storagetype:portgroupname = os-pg1-pg'), or
        can be chosen from a list provided in the cinder.conf

        :param extra_specs: extra specifications
        :param pool_record: pool record
        :returns: dict -- the extra specifications dictionary
        """
        # set extra_specs from pool_record
        extra_specs[utils.SRP] = pool_record['srpName']
        extra_specs[utils.ARRAY] = pool_record['SerialNumber']
        try:
            if not extra_specs.get(utils.PORTGROUPNAME):
                extra_specs[utils.PORTGROUPNAME] = pool_record['PortGroup']
        except Exception:
            error_message = (_("Port group name has not been provided - "
                               "please configure the "
                               "'storagetype:portgroupname' extra spec on "
                               "the volume type, or enter a list of "
                               "portgroups in the cinder.conf associated with "
                               "this backend."))
            LOG.error(error_message)
            raise exception.VolumeBackendAPIException(message=error_message)

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
            if extra_specs.get(utils.DISABLECOMPRESSION):
                # If not True remove it.
                if not strutils.bool_from_string(
                        extra_specs[utils.DISABLECOMPRESSION]):
                    extra_specs.pop(utils.DISABLECOMPRESSION, None)
        else:
            extra_specs.pop(utils.DISABLECOMPRESSION, None)

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
            # If we cannot successfully delete the volume, then we want to
            # return the volume to the default storage group,
            # which should be the SG it previously belonged to.
            self.masking.add_volume_to_default_storage_group(
                array, device_id, volume_name, extra_specs)

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
        # Cleanup remote replication
        if self.utils.is_replication_enabled(extra_specs):
            self.cleanup_lun_replication(volume, volume_name,
                                         device_id, extra_specs)
        # Remove from any storage groups
        self.masking.remove_and_reset_members(
            array, volume, device_id, volume_name, extra_specs, False)

    def get_target_wwns_from_masking_view(
            self, volume, connector):
        """Find target WWNs via the masking view.

        :param volume: volume to be attached
        :param connector: the connector dict
        :returns: list -- the target WWN list
        """
        metro_wwns = []
        host = connector['host']
        short_host_name = self.utils.get_host_short_name(host)
        extra_specs = self._initial_setup(volume)
        rep_extra_specs = self._get_replication_extra_specs(
            extra_specs, self.rep_config)
        if self.utils.is_volume_failed_over(volume):
            extra_specs = rep_extra_specs
        device_id = self._find_device_on_array(volume, extra_specs)
        target_wwns = self._get_target_wwns_from_masking_view(
            device_id, short_host_name, extra_specs)
        if self.utils.is_metro_device(self.rep_config, extra_specs):
            remote_device_id = self.get_remote_target_device(
                extra_specs[utils.ARRAY], volume, device_id)[0]
            metro_wwns = self._get_target_wwns_from_masking_view(
                remote_device_id, short_host_name, rep_extra_specs)
        return target_wwns, metro_wwns

    def _get_target_wwns_from_masking_view(
            self, device_id, short_host_name, extra_specs):
        """Helper function to get wwns from a masking view.

        :param device_id: the device id
        :param short_host_name: the short host name
        :param extra_specs: the extra specs
        :return: target wwns -- list
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

    def _get_ip_and_iqn(self, array, port):
        """Get ip and iqn from the director port.

        :param array: the array serial number
        :param port: the director port on the array
        :returns: ip_and_iqn - dict
        """
        ip_iqn_list = []
        ip_addresses, iqn = self.rest.get_iscsi_ip_address_and_iqn(
            array, port)
        for ip in ip_addresses:
            ip_iqn_list.append({'iqn': iqn, 'ip': ip})
        return ip_iqn_list

    def _find_ip_and_iqns(self, array, port_group_name):
        """Find the list of ips and iqns for the ports in a portgroup.

        :param array: the array serial number
        :param port_group_name: the portgroup name
        :returns: ip_and_iqn - list of dicts
        """
        ips_and_iqns = []
        LOG.debug("The portgroup name for iscsiadm is %(pg)s",
                  {'pg': port_group_name})
        ports = self.rest.get_port_ids(array, port_group_name)
        for port in ports:
            ip_and_iqn = self._get_ip_and_iqn(array, port)
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
        target_device_id = None
        clone_id = clone_volume.id
        clone_name = self.utils.get_volume_element_name(clone_id)
        create_snap = False
        # PowerMax/VMAX supports using a target volume that is bigger than
        # the source volume, so we create the target volume the desired
        # size at this point to avoid having to extend later
        try:
            clone_dict = self._create_volume(
                clone_name, clone_volume.size, extra_specs)
            target_device_id = clone_dict['device_id']
            LOG.info("The target device id is: %(device_id)s.",
                     {'device_id': target_device_id})
            if not snap_name:
                snap_name = self.utils.get_temp_snap_name(source_device_id)
                create_snap = True
            self.provision.create_volume_replica(
                array, source_device_id, target_device_id,
                snap_name, extra_specs, create_snap)
        except Exception as e:
            if target_device_id:
                LOG.warning("Create replica failed. Cleaning up the target "
                            "volume. Clone name: %(cloneName)s, Error "
                            "received is %(e)s.",
                            {'cloneName': clone_name, 'e': e})
                self._cleanup_target(
                    array, target_device_id, source_device_id,
                    clone_name, snap_name, extra_specs)
                # Re-throw the exception.
            raise
        # add source id and snap_name to the clone dict
        clone_dict['source_device_id'] = source_device_id
        clone_dict['snap_name'] = snap_name
        return clone_dict

    def _cleanup_target(
            self, array, target_device_id, source_device_id,
            clone_name, snap_name, extra_specs, generation=0):
        """Cleanup target volume on failed clone/ snapshot creation.

        :param array: the array serial number
        :param target_device_id: the target device ID
        :param source_device_id: the source device ID
        :param clone_name: the name of the clone volume
        :param extra_specs: the extra specifications
        :param generation: the generation number of the snapshot
        """
        snap_session = self.rest.get_sync_session(
            array, source_device_id, snap_name, target_device_id, generation)
        if snap_session:
            self.provision.break_replication_relationship(
                array, target_device_id, source_device_id,
                snap_name, extra_specs, generation)
        self._delete_from_srp(
            array, target_device_id, clone_name, extra_specs)

    def _sync_check(self, array, device_id, extra_specs,
                    tgt_only=False, source_device_id=None):
        """Check if volume is part of a SnapVx sync process.

        :param array: the array serial number
        :param device_id: volume instance
        :param tgt_only: Flag - return only sessions where device is target
        :param extra_specs: extra specifications
        :param tgt_only: Flag to specify if it is a target
        :param source_device_id: source_device_id if it has one
        """
        if not source_device_id and tgt_only:
            source_device_id = self._get_target_source_device(
                array, device_id, tgt_only)
        if source_device_id:
            @coordination.synchronized("emc-source-{source_device_id}")
            def do_unlink_and_delete_snap(source_device_id):
                self._do_sync_check(
                    array, device_id, extra_specs, tgt_only)

            do_unlink_and_delete_snap(source_device_id)
        else:
            self._do_sync_check(
                array, device_id, extra_specs, tgt_only)

    def _do_sync_check(
            self, array, device_id, extra_specs, tgt_only=False):
        """Check if volume is part of a SnapVx sync process.

        :param array: the array serial number
        :param device_id: volume instance
        :param tgt_only: Flag - return only sessions where device is target
        :param extra_specs: extra specifications
        :param tgt_only: Flag to specify if it is a target
        """
        get_sessions = False
        snapvx_tgt, snapvx_src, __ = self.rest.is_vol_in_rep_session(
            array, device_id)
        if snapvx_tgt:
            get_sessions = True
        elif snapvx_src and not tgt_only:
            get_sessions = True
        if get_sessions:
            snap_vx_sessions = self.rest.find_snap_vx_sessions(
                array, device_id, tgt_only)
            if snap_vx_sessions:
                snap_vx_sessions.sort(
                    key=lambda k: k['generation'], reverse=True)
                for session in snap_vx_sessions:
                    source = session['source_vol']
                    snap_name = session['snap_name']
                    targets = session['target_vol_list']
                    generation = session['generation']
                    # Break the replication relationship
                    for target in targets:
                        LOG.debug("Unlinking source from target. Source: "
                                  "%(volume)s, Target: %(target)s, "
                                  "generation: %(generation)s.",
                                  {'volume': source, 'target': target[0],
                                   'generation': generation})
                        self.provision.break_replication_relationship(
                            array, target[0], source, snap_name,
                            extra_specs, generation)
                    # The snapshot name will only have 'temp' (or EMC_SMI for
                    # legacy volumes) if it is a temporary volume.
                    # Only then is it a candidate for deletion.
                    if 'temp' in snap_name or 'EMC_SMI' in snap_name:
                        LOG.debug("Deleting temporary snapshot. Source: "
                                  "%(volume)s, snap name: %(snap_name)s, "
                                  "generation: %(generation)s.",
                                  {'volume': source, 'snap_name': snap_name,
                                   'generation': generation})
                        self.provision.delete_temp_volume_snap(
                            array, snap_name, source, generation)

    def _get_target_source_device(
            self, array, device_id, tgt_only=False):
        """Get the source device id of the target.

        :param array: the array serial number
        :param device_id: volume instance
        :param tgt_only: Flag - return only sessions where device is target
        return source_device_id
        """
        LOG.debug("Getting source device id from target %(target)s.",
                  {'target': device_id})
        get_sessions = False
        source_device_id = None
        snapvx_tgt, snapvx_src, __ = self.rest.is_vol_in_rep_session(
            array, device_id)
        if snapvx_tgt:
            get_sessions = True
        elif snapvx_src and not tgt_only:
            get_sessions = True
        if get_sessions:
            snap_vx_sessions = self.rest.find_snap_vx_sessions(
                array, device_id, tgt_only)
            if snap_vx_sessions:
                snap_vx_sessions.sort(
                    key=lambda k: k['generation'], reverse=True)
                for session in snap_vx_sessions:
                    source_device_id = session['source_vol']
                    break
        return source_device_id

    def _clone_check(self, array, device_id, extra_specs):
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
                snap_vx_sessions = self.rest.find_snap_vx_sessions(
                    array, src_device_id)
                if snap_vx_sessions:
                    snap_vx_sessions.sort(
                        key=lambda k: k['generation'], reverse=True)
                    self._break_relationship(
                        snap_vx_sessions, snapvx_tgt, src_device_id, array,
                        extra_specs)

            do_unlink_and_delete_snap(device_id)

    def _break_relationship(
            self, snap_vx_sessions, snapvx_tgt, snapvx_src, array,
            extra_specs):
        """Break relationship and cleanup

        :param snap_vx_sessions: the snapvx sessions
        :param snapvx_tgt: the snapvx target
        :param snapvx_src: the snapvx source
        :param array: the serialnumber of the array
        :param extra_specs: extra specifications
        """
        count = 0
        for session in snap_vx_sessions:
            snap_name = session['snap_name']
            targets = session['target_vol_list']
            # Only unlink a set number of targets
            if count == self.snapvx_unlink_limit:
                break
            is_temp = False
            is_temp = 'temp' in snap_name or 'EMC_SMI' in snap_name
            if utils.CLONE_SNAPSHOT_NAME in snap_name:
                is_temp = False
            for target in targets:
                if snapvx_src:
                    if not is_temp and target[1] == "Copied":
                        # Break the replication relationship
                        LOG.debug("Unlinking source from "
                                  "target. Source: %(volume)s, "
                                  "Target: %(target)s.",
                                  {'volume': session['source_vol'],
                                   'target': target[0]})
                        self.provision.break_replication_relationship(
                            array, target[0], session['source_vol'],
                            snap_name, extra_specs,
                            session['generation'])
                        count = count + 1
                elif snapvx_tgt:
                    # If our device is a target, we need to wait
                    # and then unlink
                    self._break_relationship_snapvx_tgt(
                        session, target, is_temp, array, extra_specs)

    def _break_relationship_snapvx_tgt(
            self, session, target, is_temp, array, extra_specs):
        """Break relationship of the snapvx target and cleanup

        :param session: the snapvx session
        :param target: the snapvx target
        :param is_temp: is the snapshot temporary
        :param array: the serialnumber of the array
        :param extra_specs: extra specifications
        """
        LOG.debug("Unlinking source from "
                  "target. Source: %(volume)s, "
                  "Target: %(target)s.",
                  {'volume': session['source_vol'],
                   'target': target[0]})
        self.provision.break_replication_relationship(
            array, target[0], session['source_vol'], session['snap_name'],
            extra_specs, session['generation'])
        # For older styled temp snapshots for clone
        # do a delete as well
        if is_temp:
            self.provision.delete_temp_volume_snap(
                array, session['snap_name'], session['source_vol'],
                session['generation'])

    def manage_existing(self, volume, external_ref):
        """Manages an existing PowerMax/VMAX Volume (import to Cinder).

        Renames the existing volume to match the expected name for the volume.
        Also need to consider things like QoS, Emulation, account/tenant.
        :param volume: the volume object including the volume_type_id
        :param external_ref: reference to the existing volume
        :returns: dict -- model_update
        """
        LOG.info("Beginning manage existing volume process")
        rep_info_dict = {}
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
                  {'vol': orig_vol_name,
                   'sg_name': src_sg})
        extra_specs = self._initial_setup(volume)

        volume_name = self.utils.get_volume_element_name(volume_id)
        # Rename the volume
        LOG.debug("Rename volume %(vol)s to %(element_name)s.",
                  {'vol': orig_vol_name,
                   'element_name': volume_name})
        self.rest.rename_volume(array, device_id, volume_name)
        provider_location = {'device_id': device_id, 'array': array}
        model_update = {'provider_location': six.text_type(provider_location)}

        # Set-up volume replication, if enabled
        if self.utils.is_replication_enabled(extra_specs):
            rep_update, rep_info_dict = self._replicate_volume(
                volume, volume_name, provider_location,
                extra_specs, delete_src=False)
            model_update.update(rep_update)

        else:
            try:
                # Add/move volume to default storage group
                self.masking.add_volume_to_default_storage_group(
                    array, device_id, volume_name, extra_specs, src_sg=src_sg)
            except Exception as e:
                exception_message = (_(
                    "Unable to move the volume to the default SG. "
                    "Exception received was %(e)s") % {'e': six.text_type(e)})
                LOG.error(exception_message)
                # Try to rename the volume back to the original name
                LOG.debug("Rename volume %(vol)s back to %(element_name)s.",
                          {'vol': volume_id,
                           'element_name': orig_vol_name})
                self.rest.rename_volume(array, device_id, orig_vol_name)
                raise exception.VolumeBackendAPIException(
                    message=exception_message)

        self.volume_metadata.capture_manage_existing(
            volume, rep_info_dict, device_id, extra_specs)

        return model_update

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
        if device_id is None:
            LOG.error("Cannot find Volume: %(id)s for "
                      "unmanage operation. Exiting...",
                      {'id': volume_id})
        else:
            # Check if volume is snap source
            self._sync_check(extra_specs['array'], device_id, extra_specs)
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

        if not self.rest.get_volume_snap(array, device_id, snap_name):
            exception_message = (
                _("Snapshot %(snap_name)s is not associated with specified "
                  "volume %(device_id)s, it is not possible to manage a "
                  "snapshot that is not associated with the specified "
                  "volume.")
                % {'device_id': device_id, 'snap_name': snap_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        snap_backend_name = self.utils.modify_snapshot_prefix(
            snap_name, manage=True)

        try:
            self.rest.modify_volume_snap(
                array, device_id, device_id, snap_name,
                extra_specs, rename=True, new_snap_name=snap_backend_name)

        except Exception as e:
            exception_message = (
                _("There was an issue managing %(snap_name)s, it was not "
                  "possible to add the OS- prefix. Error Message: %(e)s.")
                % {'snap_name': snap_name, 'e': six.text_type(e)})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        prov_loc = {'source_id': device_id, 'snap_name': snap_backend_name}

        updates = {'display_name': snap_display_name,
                   'provider_location': six.text_type(prov_loc)}

        LOG.info("Managing SnapVX Snapshot %(snap_name)s of source "
                 "volume %(device_id)s, OpenStack Snapshot display name: "
                 "%(snap_display_name)s", {
                     'snap_name': snap_name, 'device_id': device_id,
                     'snap_display_name': snap_display_name})

        return updates

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
        device_id, snap_name = self._parse_snap_info(array, snapshot)

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
                rename=True, new_snap_name=new_snap_backend_name)
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
        :return: List of dicts containing all volumes valid for management
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
        :return: manageable_vols -Sorted list of dicts
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
        :return: List of dicts containing all snapshots valid for management
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
                     "before snashot can be created and managed into Cinder.")
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
        :return: List of dicts containing all snapshots valid for management
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

        :return: List of dicts containing all snapshots valid for management
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
                    'generation': snap_info['generation'],
                    'secured': snap_info['secured'],
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
        vol_is_replicated = self.utils.is_replication_enabled(extra_specs)
        # Check if old type and new type have different replication types
        do_change_replication = self.utils.change_replication(
            vol_is_replicated, new_type)
        is_compression_disabled = self.utils.is_compression_disabled(
            extra_specs)
        # Check if old type and new type have different compression types
        do_change_compression = (self.utils.change_compression_type(
            is_compression_disabled, new_type))
        is_valid, target_slo, target_workload = (
            self._is_valid_for_storage_assisted_migration(
                device_id, host, extra_specs[utils.ARRAY],
                extra_specs[utils.SRP], volume_name,
                do_change_compression, do_change_replication))

        if not is_valid:
            # Check if this is multiattach retype case
            do_change_multiattach = self.utils.change_multiattach(
                extra_specs, new_type['extra_specs'])
            if do_change_multiattach:
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
        model_update, rep_mode, move_target, success = None, None, False, False
        target_extra_specs = new_type['extra_specs']
        target_extra_specs[utils.SRP] = srp
        target_extra_specs[utils.ARRAY] = array
        target_extra_specs[utils.SLO] = target_slo
        target_extra_specs[utils.WORKLOAD] = target_workload
        target_extra_specs[utils.INTERVAL] = extra_specs[utils.INTERVAL]
        target_extra_specs[utils.RETRIES] = extra_specs[utils.RETRIES]
        is_compression_disabled = self.utils.is_compression_disabled(
            target_extra_specs)

        if self.rep_config and self.rep_config.get('mode'):
            rep_mode = self.rep_config['mode']
            target_extra_specs[utils.REP_MODE] = rep_mode
        was_rep_enabled = self.utils.is_replication_enabled(extra_specs)
        is_rep_enabled = self.utils.is_replication_enabled(target_extra_specs)

        if volume.attach_status == 'attached':
            # Scenario: Rep was enabled, target VT has rep disabled, need to
            # disable replication
            if was_rep_enabled and not is_rep_enabled:
                self.cleanup_lun_replication(volume, volume_name,
                                             device_id, extra_specs)
                model_update = {
                    'replication_status': REPLICATION_DISABLED,
                    'replication_driver_data': None}

            # Scenario: Rep was not enabled, target VT has rep enabled, need to
            # enable replication
            elif not was_rep_enabled and is_rep_enabled:
                rep_status, rep_driver_data, rep_info_dict = (
                    self.setup_inuse_volume_replication(
                        array, volume, device_id, extra_specs))
                model_update = {
                    'replication_status': rep_status,
                    'replication_driver_data': six.text_type(rep_driver_data)}

            # Retype the device on the source array
            success, target_sg_name = self._retype_inuse_volume(
                array, srp, volume, device_id, extra_specs,
                target_slo, target_workload, target_extra_specs,
                is_compression_disabled)

            # If the volume was replication enabled both before and after
            # retype, the volume needs to be retyped on the remote array also
            if was_rep_enabled and is_rep_enabled:
                success = self._retype_remote_volume(
                    array, volume, device_id, volume_name,
                    rep_mode, is_rep_enabled, target_extra_specs)

        # Volume is not attached, retype as normal
        elif volume.attach_status != 'attached':
            if was_rep_enabled:
                if not is_rep_enabled:
                    # Disable replication is True
                    self._remove_vol_and_cleanup_replication(
                        array, device_id, volume_name, extra_specs, volume)
                    model_update = {'replication_status': REPLICATION_DISABLED,
                                    'replication_driver_data': None}
                else:
                    # Ensure both source and target volumes are retyped
                    move_target = True
            else:
                if is_rep_enabled:
                    # Setup_volume_replication will put volume in correct sg
                    rep_status, rdf_dict, __ = self.setup_volume_replication(
                        array, volume, device_id, target_extra_specs)
                    model_update = {
                        'replication_status': rep_status,
                        'replication_driver_data': six.text_type(rdf_dict)}
                    return True, model_update

            try:
                target_sg_name = (
                    self.masking.get_or_create_default_storage_group(
                        array, srp, target_slo, target_workload, extra_specs,
                        is_compression_disabled, is_rep_enabled, rep_mode))
            except Exception as e:
                LOG.error("Failed to get or create storage group. "
                          "Exception received was %(e)s.", {'e': e})
                return False

            success = self._retype_volume(
                array, device_id, volume_name, target_sg_name,
                volume, target_extra_specs)

            if move_target:
                success = self._retype_remote_volume(
                    array, volume, device_id, volume_name,
                    rep_mode, is_rep_enabled, target_extra_specs)

        if success:
            self.volume_metadata.capture_retype_info(
                volume, device_id, array, srp, target_slo,
                target_workload, target_sg_name, is_rep_enabled, rep_mode,
                is_compression_disabled)

        return success, model_update

    def _retype_volume(self, array, device_id, volume_name, target_sg_name,
                       volume, extra_specs):
        """Move the volume to the correct storagegroup.

        Add the volume to the target storage group, or to the correct default
        storage group, and check if it is there.
        :param array: the array serial
        :param device_id: the device id
        :param volume_name: the volume name
        :param target_sg_name: the target sg name
        :param volume: the volume object
        :param extra_specs: the target extra specifications
        :returns bool
        """
        storagegroups = self.rest.get_storage_groups_from_volume(
            array, device_id)
        if not storagegroups:
            LOG.warning("Volume : %(volume_name)s does not currently "
                        "belong to any storage groups.",
                        {'volume_name': volume_name})
            # Add the volume to the target storage group
            self.masking.add_volume_to_storage_group(
                array, device_id, target_sg_name, volume_name, extra_specs)
            # Check if volume should be member of GVG
            self.masking.return_volume_to_volume_group(
                array, volume, device_id, volume_name, extra_specs)
        else:
            # Move the volume to the correct default storage group for
            # its volume type
            self.masking.remove_and_reset_members(
                array, volume, device_id, volume_name,
                extra_specs, reset=True)

        # Check that it has been added.
        vol_check = self.rest.is_volume_in_storagegroup(
            array, device_id, target_sg_name)
        if not vol_check:
            LOG.error(
                "Volume: %(volume_name)s has not been "
                "added to target storage group %(storageGroup)s.",
                {'volume_name': volume_name,
                 'storageGroup': target_sg_name})
            return False

        return True

    def _retype_inuse_volume(self, array, srp, volume, device_id, extra_specs,
                             target_slo, target_workload, target_extra_specs,
                             is_compression_disabled):
        """Retype an in-use volume using storage assisted migration.

        :param array: the array serial
        :param srp: the SRP ID
        :param volume: the volume object
        :param device_id: the device id
        :param extra_specs: the source volume type extra specs
        :param target_slo: the service level of the target volume type
        :param target_workload: the workload of the target volume type
        :param target_extra_specs: the target extra specs
        :param is_compression_disabled: if compression is disabled in the
        target volume type
        :return: if the retype was successful -- bool,
                 the storage group the volume has moved to --str
        """
        success = False
        device_info = self.rest.get_volume(array, device_id)
        source_sg_name = device_info['storageGroupId'][0]
        source_sg = self.rest.get_storage_group(array, source_sg_name)
        target_extra_specs[utils.PORTGROUPNAME] = extra_specs[
            utils.PORTGROUPNAME]

        attached_host = self.utils.get_volume_attached_hostname(device_info)
        if not attached_host:
            LOG.error(
                "There was an issue retrieving attached host from volume "
                "%(volume_name)s, aborting storage-assisted migration.",
                {'volume_name': device_id})
            return False, None

        target_sg_name, __, __, __ = self.utils.get_child_sg_name(
            attached_host, target_extra_specs)
        target_sg = self.rest.get_storage_group(array, target_sg_name)

        if not target_sg:
            self.provision.create_storage_group(array, target_sg_name, srp,
                                                target_slo,
                                                target_workload,
                                                target_extra_specs,
                                                is_compression_disabled)
            parent_sg = source_sg['parent_storage_group'][0]
            self.masking.add_child_sg_to_parent_sg(
                array, target_sg_name, parent_sg, target_extra_specs)
            target_sg = self.rest.get_storage_group(array, target_sg_name)

        target_in_parent = self.rest.is_child_sg_in_parent_sg(
            array, target_sg_name, target_sg['parent_storage_group'][0])

        if target_sg and target_in_parent:
            self.masking.move_volume_between_storage_groups(
                array, device_id, source_sg_name, target_sg_name,
                target_extra_specs)
            success = self.rest.is_volume_in_storagegroup(
                array, device_id, target_sg_name)

        if not success:
            LOG.error(
                "Volume: %(volume_name)s has not been "
                "added to target storage group %(storageGroup)s.",
                {'volume_name': device_id,
                 'storageGroup': target_sg_name})
        else:
            LOG.info("Move successful: %(success)s", {'success': success})

        return success, target_sg_name

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
        (target_device, remote_array, _, _, _) = (
            self.get_remote_target_device(array, volume, device_id))
        rep_extra_specs = self._get_replication_extra_specs(
            extra_specs, self.rep_config)
        rep_compr_disabled = self.utils.is_compression_disabled(
            rep_extra_specs)
        remote_sg_name = self.masking.get_or_create_default_storage_group(
            remote_array, rep_extra_specs[utils.SRP],
            rep_extra_specs[utils.SLO], rep_extra_specs[utils.WORKLOAD],
            rep_extra_specs, rep_compr_disabled,
            is_re=is_re, rep_mode=rep_mode)
        found_storage_group_list = self.rest.get_storage_groups_from_volume(
            remote_array, target_device)
        move_rqd = True
        for found_storage_group_name in found_storage_group_list:
            # Check if remote volume is already in the correct sg
            if found_storage_group_name == remote_sg_name:
                move_rqd = False
                break
        if move_rqd:
            success = self._retype_volume(
                remote_array, target_device, volume_name, remote_sg_name,
                volume, rep_extra_specs)
        return success

    def _is_valid_for_storage_assisted_migration(
            self, device_id, host, source_array, source_srp, volume_name,
            do_change_compression, do_change_replication):
        """Check if volume is suitable for storage assisted (pool) migration.

        :param device_id: the volume device id
        :param host: the host dict
        :param source_array: the volume's current array serial number
        :param source_srp: the volume's current pool name
        :param volume_name: the name of the volume to be migrated
        :param do_change_compression: do change compression
        :param do_change_replication: flag indicating replication change
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

        if target_array_serial not in source_array:
            LOG.error(
                "The source array: %(source_array)s does not "
                "match the target array: %(target_array)s - "
                "skipping storage-assisted migration.",
                {'source_array': source_array,
                 'target_array': target_array_serial})
            return false_ret

        if target_srp not in source_srp:
            LOG.error(
                "Only SLO/workload migration within the same SRP Pool is "
                "supported in this version. The source pool: "
                "%(source_pool_name)s does not match the target array: "
                "%(target_pool)s. Skipping storage-assisted migration.",
                {'source_pool_name': source_srp,
                 'target_pool': target_srp})
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

    def setup_volume_replication(self, array, volume, device_id,
                                 extra_specs, target_device_id=None):
        """Setup replication for volume, if enabled.

        Called on create volume, create cloned volume, create volume from
        snapshot, manage_existing, and re-establishing a replication
        relationship after extending.
        :param array: the array serial number
        :param volume: the volume object
        :param device_id: the device id
        :param extra_specs: the extra specifications
        :param target_device_id: the target device id
        :returns: replication_status -- str, replication_driver_data -- dict
                  rep_info_dict -- dict
        """
        rep_extra_specs = {'rep_mode': None}
        source_name = volume.name
        LOG.debug('Starting replication setup '
                  'for volume: %s.', source_name)
        # Get rdf details
        rdf_group_no, remote_array = self.get_rdf_details(array)
        rdf_vol_size = volume.size
        if rdf_vol_size == 0:
            rdf_vol_size = self.rest.get_size_of_device_on_array(
                array, device_id)

        # Give the target volume the same Volume Element Name as the
        # source volume
        target_name = self.utils.get_volume_element_name(volume.id)

        if not target_device_id:
            # Create a target volume on the target array
            rep_extra_specs = self._get_replication_extra_specs(
                extra_specs, self.rep_config)
            volume_dict = self._create_volume(
                target_name, rdf_vol_size, rep_extra_specs)
            target_device_id = volume_dict['device_id']

        LOG.debug("Create volume replica: Target device: %(target)s "
                  "Source Device: %(source)s "
                  "Volume identifier: %(name)s.",
                  {'target': target_device_id,
                   'source': device_id,
                   'name': target_name})

        # Enable rdf replication and establish the link
        rdf_dict = self.enable_rdf(
            array, volume, device_id, rdf_group_no, self.rep_config,
            target_name, remote_array, target_device_id, extra_specs)

        if self.utils.does_vol_need_rdf_management_group(extra_specs):
            self._add_volume_to_async_rdf_managed_grp(
                array, device_id, source_name, remote_array,
                target_device_id, extra_specs)

        LOG.info('Successfully setup replication for %s.',
                 target_name)
        replication_status = REPLICATION_ENABLED
        replication_driver_data = rdf_dict
        rep_info_dict = self.volume_metadata.gather_replication_info(
            volume.id, 'replication', False,
            rdf_group_no=rdf_group_no,
            target_name=target_name, remote_array=remote_array,
            target_device_id=target_device_id,
            replication_status=replication_status,
            rep_mode=rep_extra_specs['rep_mode'],
            rdf_group_label=self.rep_config['rdf_group_label'])

        return replication_status, replication_driver_data, rep_info_dict

    def setup_inuse_volume_replication(self, array, volume, device_id,
                                       extra_specs):
        """Setup replication for in-use volume.

        :param array: the array serial number
        :param volume: the volume object
        :param device_id: the device id
        :param extra_specs: the extra specifications
        :return: replication_status -- str, replication_driver_data -- dict
                 rep_info_dict -- dict
        """
        source_name = volume.name
        LOG.debug('Starting replication setup '
                  'for volume: %s.', source_name)
        rdf_group_no, remote_array = self.get_rdf_details(array)
        extra_specs['replication_enabled'] = '<is> True'
        extra_specs['rep_mode'] = self.rep_config['mode']

        rdf_vol_size = volume.size
        if rdf_vol_size == 0:
            rdf_vol_size = self.rest.get_size_of_device_on_array(
                array, device_id)

        target_name = self.utils.get_volume_element_name(volume.id)

        rep_extra_specs = self._get_replication_extra_specs(
            extra_specs, self.rep_config)
        volume_dict = self._create_volume(
            target_name, rdf_vol_size, rep_extra_specs, in_use=True)
        target_device_id = volume_dict['device_id']

        LOG.debug("Create volume replica: Target device: %(target)s "
                  "Source Device: %(source)s "
                  "Volume identifier: %(name)s.",
                  {'target': target_device_id,
                   'source': device_id,
                   'name': target_name})

        self._sync_check(array, device_id, extra_specs, tgt_only=True)
        rdf_dict = self.rest.create_rdf_device_pair(
            array, device_id, rdf_group_no, target_device_id, remote_array,
            extra_specs)

        LOG.info('Successfully setup replication for %s.',
                 target_name)
        replication_status = REPLICATION_ENABLED
        replication_driver_data = rdf_dict
        rep_info_dict = self.volume_metadata.gather_replication_info(
            volume.id, 'replication', False,
            rdf_group_no=rdf_group_no,
            target_name=target_name, remote_array=remote_array,
            target_device_id=target_device_id,
            replication_status=replication_status,
            rep_mode=rep_extra_specs['rep_mode'],
            rdf_group_label=self.rep_config['rdf_group_label'],
            target_array_model=rep_extra_specs['target_array_model'])

        return replication_status, replication_driver_data, rep_info_dict

    def _add_volume_to_async_rdf_managed_grp(
            self, array, device_id, volume_name, remote_array,
            target_device_id, extra_specs):
        """Add an async volume to its rdf management group.

        :param array: the array serial number
        :param device_id: the device id
        :param volume_name: the volume name
        :param remote_array: the remote array
        :param target_device_id: the target device id
        :param extra_specs: the extra specifications
        :raises: VolumeBackendAPIException
        """
        group_name = self.utils.get_async_rdf_managed_grp_name(
            self.rep_config)
        try:
            self.provision.get_or_create_group(array, group_name, extra_specs)
            self.masking.add_volume_to_storage_group(
                array, device_id, group_name, volume_name, extra_specs)
            # Add remote volume
            self.provision.get_or_create_group(
                remote_array, group_name, extra_specs)
            self.masking.add_volume_to_storage_group(
                remote_array, target_device_id,
                group_name, volume_name, extra_specs)
        except Exception as e:
            exception_message = (
                _('Exception occurred adding volume %(vol)s to its async '
                  'rdf management group - the exception received was: %(e)s')
                % {'vol': volume_name, 'e': six.text_type(e)})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

    def cleanup_lun_replication(self, volume, volume_name,
                                device_id, extra_specs):
        """Cleanup target volume on delete.

        Extra logic if target is last in group, or is a metro volume.
        :param volume: the volume object
        :param volume_name: the volume name
        :param device_id: the device id
        :param extra_specs: extra specifications
        :raises: VolumeBackendAPIException
        """
        LOG.debug('Starting cleanup replication from volume: '
                  '%s.', volume_name)
        try:
            loc = volume.provider_location
            rep_data = volume.replication_driver_data

            if (isinstance(loc, six.string_types)
                    and isinstance(rep_data, six.string_types)):
                name = ast.literal_eval(loc)
                try:
                    array = name['array']
                except KeyError:
                    array = (name['keybindings']
                             ['SystemName'].split('+')[1].strip('-'))
                rep_extra_specs = self._get_replication_extra_specs(
                    extra_specs, self.rep_config)
                (target_device, remote_array, rdf_group_no,
                 local_vol_state, pair_state) = (
                    self.get_remote_target_device(array, volume, device_id))

                if target_device is not None:
                    # Clean-up target
                    self._cleanup_remote_target(
                        array, volume, remote_array, device_id, target_device,
                        rdf_group_no, volume_name, rep_extra_specs)
                    LOG.info('Successfully destroyed replication for '
                             'volume: %(volume)s',
                             {'volume': volume_name})
                else:
                    LOG.warning('Replication target not found for '
                                'replication-enabled volume: %(volume)s',
                                {'volume': volume_name})
        except Exception as e:
            if extra_specs.get(utils.REP_MODE, None) in [
                    utils.REP_ASYNC, utils.REP_METRO]:
                (target_device, remote_array, rdf_group_no,
                 local_vol_state, pair_state) = (
                    self.get_remote_target_device(
                        extra_specs[utils.ARRAY], volume, device_id))
                if target_device is not None:
                    # Return devices to their async rdf management groups
                    self._add_volume_to_async_rdf_managed_grp(
                        extra_specs[utils.ARRAY], device_id, volume_name,
                        remote_array, target_device, extra_specs)
            exception_message = (
                _('Cannot get necessary information to cleanup '
                  'replication target for volume: %(volume)s. '
                  'The exception received was: %(e)s. Manual '
                  'clean-up may be required. Please contact '
                  'your administrator.')
                % {'volume': volume_name, 'e': six.text_type(e)})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

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
        self.masking.remove_and_reset_members(
            remote_array, volume, target_device, volume_name,
            rep_extra_specs, False)
        are_vols_paired, local_vol_state, pair_state = (
            self.rest.are_vols_rdf_paired(
                array, remote_array, device_id, target_device))
        if are_vols_paired:
            is_metro = self.utils.is_metro_device(
                self.rep_config, rep_extra_specs)
            if is_metro:
                rep_extra_specs['allow_del_metro'] = self.allow_delete_metro
                self._cleanup_metro_target(
                    array, device_id, target_device,
                    rdf_group, rep_extra_specs)
            else:
                # Break the sync relationship.
                self.provision.break_rdf_relationship(
                    array, device_id, target_device, rdf_group,
                    rep_extra_specs, pair_state)
        self._delete_from_srp(
            remote_array, target_device, volume_name, rep_extra_specs)

    @coordination.synchronized('emc-rg-{rdf_group}')
    def _cleanup_metro_target(self, array, device_id, target_device,
                              rdf_group, rep_extra_specs):
        """Helper function to cleanup a metro remote target.

        :param array: the array serial number
        :param device_id: the device id
        :param target_device: the target device id
        :param rdf_group: the rdf group number
        :param rep_extra_specs: the rep extra specs
        """
        if rep_extra_specs['allow_del_metro']:
            metro_grp = self.utils.get_async_rdf_managed_grp_name(
                self.rep_config)
            self.provision.break_metro_rdf_pair(
                array, device_id, target_device, rdf_group,
                rep_extra_specs, metro_grp)
            # Remove the volume from the metro_grp
            self.masking.remove_volume_from_sg(array, device_id, 'metro_vol',
                                               metro_grp, rep_extra_specs)
            # Resume I/O on the RDF links for any remaining volumes
            if self.rest.get_num_vols_in_sg(array, metro_grp) > 0:
                LOG.info("Resuming I/O for all volumes in the RDF group: "
                         "%(rdfg)s", {'rdfg': device_id})
                self.provision.enable_group_replication(
                    array, metro_grp, rdf_group,
                    rep_extra_specs, establish=True)
        else:
            exception_message = (
                _("Deleting a Metro-protected replicated volume is "
                  "not permitted on this backend %(backend)s. "
                  "Please contact your administrator.")
                % {'backend': self.configuration.safe_get(
                    'volume_backend_name')})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

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
        self._sync_check(array, device_id, extra_specs)
        # Remove from any storage groups and cleanup replication
        self._remove_vol_and_cleanup_replication(
            array, device_id, volume_name, extra_specs, volume)
        self._delete_from_srp(
            array, device_id, volume_name, extra_specs)

    def get_rdf_details(self, array):
        """Retrieves an SRDF group instance.

        :param array: the array serial number
        :returns: rdf_group_no, remote_array
        """
        if not self.rep_config:
            exception_message = (_("Replication is not configured on "
                                   "backend: %(backend)s.") %
                                 {'backend': self.configuration.safe_get(
                                     'volume_backend_name')})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        remote_array = self.rep_config['array']
        rdf_group_label = self.rep_config['rdf_group_label']
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
        :raises: VolumeBackendAPIException
        """
        group_fo = None
        if secondary_id != 'default':
            if not self.failover:
                self.failover = True
                if self.rep_config:
                    secondary_id = self.rep_config['array']
            else:
                exception_message = (_(
                    "Backend %(backend)s is already failed over. "
                    "If you wish to failback, please append "
                    "'--backend_id default' to your command.")
                    % {'backend': self.configuration.safe_get(
                       'volume_backend_name')})
                LOG.error(exception_message)
                return
        else:
            if self.failover:
                self.failover = False
                secondary_id = None
                group_fo = 'default'
            else:
                exception_message = (_(
                    "Cannot failback backend %(backend)s- backend not "
                    "in failed over state. If you meant to failover, please "
                    "omit the '--backend_id default' from the command")
                    % {'backend': self.configuration.safe_get(
                       'volume_backend_name')})
                LOG.error(exception_message)
                return

        volume_update_list, group_update_list = (
            self._populate_volume_and_group_update_lists(
                volumes, groups, group_fo))

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
        rep_mode = self.rep_config['mode']
        if groups:
            for group in groups:
                vol_list = []
                for index, vol in enumerate(volumes):
                    if vol.group_id == group.id:
                        vol_list.append(volumes.pop(index))
                grp_update, vol_updates = (
                    self.failover_replication(
                        None, group, vol_list, group_fo, host=True))

                group_update_list.append({'group_id': group.id,
                                          'updates': grp_update})
                volume_update_list += vol_updates
        sync_vol_list, non_rep_vol_list, async_vol_list, metro_list = (
            [], [], [], [])
        for volume in volumes:
            array = ast.literal_eval(volume.provider_location)['array']
            extra_specs = self._initial_setup(volume)
            extra_specs[utils.ARRAY] = array
            if self.utils.is_replication_enabled(extra_specs):
                device_id = self._find_device_on_array(
                    volume, extra_specs)
                self._sync_check(
                    array, device_id, extra_specs)
                if rep_mode == utils.REP_SYNC:
                    sync_vol_list.append(volume)
                elif rep_mode == utils.REP_ASYNC:
                    async_vol_list.append(volume)
                else:
                    metro_list.append(volume)
            else:
                non_rep_vol_list.append(volume)

        if len(async_vol_list) > 0:
            vol_grp_name = self.utils.get_async_rdf_managed_grp_name(
                self.rep_config)
            __, vol_updates = (
                self._failover_replication(
                    async_vol_list, None, vol_grp_name,
                    secondary_backend_id=group_fo, host=True))
            volume_update_list += vol_updates

        if len(sync_vol_list) > 0:
            volume_update_list = self. _update_volume_list_from_sync_vol_list(
                sync_vol_list, volume_update_list, group_fo)

        if len(metro_list) > 0:
            __, vol_updates = (
                self._failover_replication(
                    sync_vol_list, None, None, secondary_backend_id=group_fo,
                    host=True, is_metro=True))
            volume_update_list += vol_updates

        if len(non_rep_vol_list) > 0:
            if self.failover:
                # Since the array has been failed-over,
                # volumes without replication should be in error.
                for vol in non_rep_vol_list:
                    volume_update_list.append({
                        'volume_id': vol.id,
                        'updates': {'status': 'error'}})
        return volume_update_list, group_update_list

    def _update_volume_list_from_sync_vol_list(
            self, sync_vol_list, volume_update_list, group_fo):
        """Update the volume update list from the synced volume list

        :param sync_vol_list: synced volume list
        :param volume_update_list: volume update list
        :param group_fo: group fail over
        :returns: volume_update_list
        """
        extra_specs = self._initial_setup(sync_vol_list[0])
        array = ast.literal_eval(
            sync_vol_list[0].provider_location)['array']
        extra_specs[utils.ARRAY] = array
        temp_grp_name = self.utils.get_temp_failover_grp_name(
            self.rep_config)
        self.provision.create_volume_group(
            array, temp_grp_name, extra_specs)
        device_ids = self._get_volume_device_ids(sync_vol_list, array)
        self.masking.add_volumes_to_storage_group(
            array, device_ids, temp_grp_name, extra_specs)
        __, vol_updates = (
            self._failover_replication(
                sync_vol_list, None, temp_grp_name,
                secondary_backend_id=group_fo, host=True))
        volume_update_list += vol_updates
        self.rest.delete_storage_group(array, temp_grp_name)
        return volume_update_list

    def get_remote_target_device(self, array, volume, device_id):
        """Get the remote target for a given volume.

        :param array: the array serial number
        :param volume: the volume object
        :param device_id: the device id
        :returns: target_device, target_array, rdf_group, state
        """
        target_device, local_vol_state, pair_state = None, '', ''
        rdf_group, remote_array = self.get_rdf_details(array)
        try:
            rep_target_data = volume.replication_driver_data
            replication_keybindings = ast.literal_eval(rep_target_data)
            remote_array = replication_keybindings['array']
            remote_device = replication_keybindings['device_id']
            target_device_info = self.rest.get_volume(
                remote_array, remote_device)
            if target_device_info is not None:
                target_device = remote_device
                are_vols_paired, local_vol_state, pair_state = (
                    self.rest.are_vols_rdf_paired(
                        array, remote_array, device_id, target_device))
                if not are_vols_paired:
                    target_device = None
        except (KeyError, ValueError):
            target_device = None
        return (target_device, remote_array, rdf_group,
                local_vol_state, pair_state)

    def extend_volume_is_replicated(
            self, array, volume, device_id, volume_name,
            new_size, extra_specs):
        """Extend a replication-enabled volume.

        Cannot extend volumes in a synchronization pair where the source
        and/or target arrays are running HyperMax versions < 5978. Must first
        break the relationship, extend them separately, then recreate the
        pair. Extending Metro protected volumes is not supported.
        :param array: the array serial number
        :param volume: the volume objcet
        :param device_id: the volume device id
        :param volume_name: the volume name
        :param new_size: the new size the volume should be
        :param extra_specs: extra specifications
        """
        ode_replication, allow_extend = False, self.extend_replicated_vol
        if (self.rest.is_next_gen_array(array)
                and not self.utils.is_metro_device(
                    self.rep_config, extra_specs)):
            # Check if remote array is next gen
            __, remote_array = self.get_rdf_details(array)
            if self.rest.is_next_gen_array(remote_array):
                ode_replication = True
        if self.utils.is_metro_device(self.rep_config, extra_specs):
            allow_extend = False
        if allow_extend is True or ode_replication is True:
            self._extend_with_or_without_ode_replication(
                array, volume, device_id, ode_replication, volume_name,
                new_size, extra_specs)
        else:
            exception_message = (_(
                "Extending a replicated volume is not permitted on this "
                "backend. Please contact your administrator. Note that "
                "you cannot extend SRDF/Metro protected volumes."))
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

    def _extend_with_or_without_ode_replication(
            self, array, volume, device_id, ode_replication, volume_name,
            new_size, extra_specs):
        """Extend a volume with or without Online Device Expansion

        :param array: the array serial number
        :param volume: the volume objcet
        :param device_id: the volume device id
        :param ode_replication: Online device expansion
        :param volume_name: the volume name
        :param new_size: the new size the volume should be
        :param extra_specs: extra specifications
        """
        try:
            (target_device, remote_array, rdf_group,
             local_vol_state, pair_state) = (
                self.get_remote_target_device(
                    array, volume, device_id))
            rep_extra_specs = self._get_replication_extra_specs(
                extra_specs, self.rep_config)
            lock_rdf_group = rdf_group
            if not ode_replication:
                # Volume must be removed from replication (storage) group
                # before the replication relationship can be ended (cannot
                # have a mix of replicated and non-replicated volumes as
                # the SRDF groups become unmanageable)
                lock_rdf_group = None
                self.masking.remove_and_reset_members(
                    array, volume, device_id, volume_name,
                    extra_specs, False)

                # Repeat on target side
                self.masking.remove_and_reset_members(
                    remote_array, volume, target_device, volume_name,
                    rep_extra_specs, False)

                LOG.info("Breaking replication relationship...")
                self.provision.break_rdf_relationship(
                    array, device_id, target_device, rdf_group,
                    rep_extra_specs, pair_state)

            # Extend the target volume
            LOG.info("Extending target volume...")
            # Check to make sure the R2 device requires extending first...
            r2_size = self.rest.get_size_of_device_on_array(
                remote_array, target_device)
            if int(r2_size) < int(new_size):
                self.provision.extend_volume(
                    remote_array, target_device, new_size,
                    rep_extra_specs, lock_rdf_group)

            # Extend the source volume
            LOG.info("Extending source volume...")
            self.provision.extend_volume(
                array, device_id, new_size, extra_specs, lock_rdf_group)

            if not ode_replication:
                # Re-create replication relationship
                LOG.info("Recreating replication relationship...")
                self.setup_volume_replication(
                    array, volume, device_id, extra_specs, target_device)

                # Check if volume needs to be returned to volume group
                if volume.group_id:
                    self._add_new_volume_to_volume_group(
                        volume, device_id, volume_name, extra_specs)

        except Exception as e:
            exception_message = (_("Error extending volume. "
                                   "Error received was %(e)s") %
                                 {'e': e})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

    def enable_rdf(self, array, volume, device_id, rdf_group_no, rep_config,
                   target_name, remote_array, target_device, extra_specs):
        """Create a replication relationship with a target volume.

        :param array: the array serial number
        :param volume: the volume object
        :param device_id: the device id
        :param rdf_group_no: the rdf group number
        :param rep_config: the replication config
        :param target_name: the target volume name
        :param remote_array: the remote array serial number
        :param target_device: the target device id
        :param extra_specs: the extra specifications
        :returns: rdf_dict
        """
        rep_extra_specs = self._get_replication_extra_specs(
            extra_specs, rep_config)
        try:
            # Remove source and target instances from their
            # default storage groups
            self.masking.remove_and_reset_members(
                array, volume, device_id, target_name, extra_specs, False)

            self.masking.remove_and_reset_members(
                remote_array, volume, target_device, target_name,
                rep_extra_specs, False)

            # Check if volume is a copy session target
            self._sync_check(array, device_id, extra_specs, tgt_only=True)
            # Establish replication relationship
            rdf_dict = self.rest.create_rdf_device_pair(
                array, device_id, rdf_group_no, target_device, remote_array,
                extra_specs)

            # Add source and target instances to their replication groups
            LOG.debug("Adding source device to default replication group.")
            self.add_volume_to_replication_group(
                array, device_id, target_name, extra_specs)
            LOG.debug("Adding target device to default replication group.")
            self.add_volume_to_replication_group(
                remote_array, target_device, target_name, rep_extra_specs)

        except Exception as e:
            LOG.warning(
                ("Remote replication failed. Cleaning up the target "
                 "volume and returning source volume to default storage "
                 "group. Volume name: %(name)s "),
                {'name': target_name})
            self._cleanup_remote_target(
                array, volume, remote_array, device_id, target_device,
                rdf_group_no, target_name, rep_extra_specs)
            # Re-throw the exception.
            exception_message = (_("Remote replication failed with exception:"
                                   " %(e)s")
                                 % {'e': six.text_type(e)})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        return rdf_dict

    def add_volume_to_replication_group(
            self, array, device_id, volume_name, extra_specs):
        """Add a volume to the default replication group.

        Replication groups are PowerMax/VMAX storage groups that contain only
        RDF-paired volumes. We can use our normal storage group operations.
        :param array: array serial number
        :param device_id: the device id
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        :returns: storagegroup_name
        """
        do_disable_compression = self.utils.is_compression_disabled(
            extra_specs)
        rep_mode = extra_specs.get(utils.REP_MODE, None)
        try:
            storagegroup_name = (
                self.masking.get_or_create_default_storage_group(
                    array, extra_specs[utils.SRP], extra_specs[utils.SLO],
                    extra_specs[utils.WORKLOAD], extra_specs,
                    do_disable_compression, is_re=True, rep_mode=rep_mode))
        except Exception as e:
            exception_message = (_("Failed to get or create replication "
                                   "group. Exception received: %(e)s")
                                 % {'e': six.text_type(e)})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        self.masking.add_volume_to_storage_group(
            array, device_id, storagegroup_name, volume_name, extra_specs)

        return storagegroup_name

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

        # If disable compression is set, check if target array is all flash
        do_disable_compression = self.utils.is_compression_disabled(
            extra_specs)
        if do_disable_compression:
            if not self.rest.is_compression_capable(
                    rep_extra_specs[utils.ARRAY]):
                rep_extra_specs.pop(utils.DISABLECOMPRESSION, None)

        # Check to see if SLO and Workload are configured on the target array.
        if extra_specs[utils.SLO]:
            rep_extra_specs['target_array_model'], next_gen = (
                self.rest.get_array_model_info(rep_config['array']))
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
        if group.is_replicated:
            if (self.rep_config and self.rep_config.get('mode')
                    and self.rep_config['mode']
                    in [utils.REP_ASYNC, utils.REP_METRO]):
                msg = _('Replication groups are not supported '
                        'for use with Asynchronous replication or Metro.')
                raise exception.InvalidInput(reason=msg)

        model_update = {'status': fields.GroupStatus.AVAILABLE}

        LOG.info("Create generic volume group: %(group)s.",
                 {'group': group.id})

        vol_grp_name = self.utils.update_volume_group_name(group)

        try:
            array, interval_retries_dict = self.utils.get_volume_group_utils(
                group, self.interval, self.retries)
            self.provision.create_volume_group(
                array, vol_grp_name, interval_retries_dict)
            if group.is_replicated:
                LOG.debug("Group: %(group)s is a replication group.",
                          {'group': group.id})
                # Create remote group
                __, remote_array = self.get_rdf_details(array)
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
        array, interval_retries_dict = self.utils.get_volume_group_utils(
            group, self.interval, self.retries)
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

        # Remove replication for group, if applicable
        if group.is_replicated:
            self._cleanup_group_replication(
                array, vol_grp_name, volume_device_ids,
                interval_retries_dict)
        try:
            if volume_device_ids:
                # First remove all the volumes from the SG
                self.masking.remove_volumes_from_storage_group(
                    array, volume_device_ids, vol_grp_name,
                    interval_retries_dict)
                for vol in volumes:
                    extra_specs = self._initial_setup(vol)
                    device_id = self._find_device_on_array(
                        vol, extra_specs)
                    if device_id in volume_device_ids:
                        self.masking.remove_and_reset_members(
                            array, vol, device_id, vol.name,
                            extra_specs, False)
                        self._delete_from_srp(
                            array, device_id, "group vol", extra_specs)
                    else:
                        LOG.debug("Volume not found on the array.")
                    # Add the device id to the deleted list
                    deleted_volume_device_ids.append(device_id)
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
            self, array, vol_grp_name, volume_device_ids, extra_specs):
        """Cleanup remote replication.

        Break and delete the rdf replication relationship and
        delete the remote storage group and member devices.
        :param array: the array serial number
        :param vol_grp_name: the volume group name
        :param volume_device_ids: the device ids of the local volumes
        :param extra_specs: the extra specifications
        """
        rdf_group_no, remote_array = self.get_rdf_details(array)
        # Delete replication for group, if applicable
        if volume_device_ids:
            self.provision.delete_group_replication(
                array, vol_grp_name, rdf_group_no, extra_specs)
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
            snapshots_model_update.append(
                {'id': snapshot.id,
                 'provider_location': six.text_type(
                     {'source_id': src_dev_id, 'snap_name': snap_name}),
                 'status': fields.SnapshotStatus.AVAILABLE})
        model_update = {'status': fields.GroupStatus.AVAILABLE}

        return model_update, snapshots_model_update

    def _get_src_device_id_for_group_snap(self, snapshot):
        """Get the source device id for the provider_location.

        :param snapshot: the snapshot object
        :return: src_device_id
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
        array, interval_retries_dict = self.utils.get_volume_group_utils(
            source_group, self.interval, self.retries)
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
            array, extra_specs = self.utils.get_volume_group_utils(
                source_group, self.interval, self.retries)
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
        :return: src_dev_ids
        """
        src_dev_ids = []
        for snap in snapshots:
            src_dev_id, snap_name = self._parse_snap_info(array, snap)
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

        array, interval_retries_dict = self.utils.get_volume_group_utils(
            group, self.interval, self.retries)
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        add_vols = [vol for vol in add_volumes] if add_volumes else []
        add_device_ids = self._get_volume_device_ids(add_vols, array)
        remove_vols = [vol for vol in remove_volumes] if remove_volumes else []
        remove_device_ids = self._get_volume_device_ids(remove_vols, array)
        vol_grp_name = None
        try:
            volume_group = self._find_volume_group(array, group)
            if volume_group:
                if 'name' in volume_group:
                    vol_grp_name = volume_group['name']
            if vol_grp_name is None:
                raise exception.GroupNotFound(group_id=group.id)
            # Add volume(s) to the group
            if add_device_ids:
                self.utils.check_rep_status_enabled(group)
                for vol in add_vols:
                    extra_specs = self._initial_setup(vol)
                    self.utils.check_replication_matched(vol, extra_specs)
                self.masking.add_volumes_to_storage_group(
                    array, add_device_ids, vol_grp_name, interval_retries_dict)
                if group.is_replicated:
                    # Add remote volumes to remote storage group
                    self.masking.add_remote_vols_to_volume_group(
                        add_vols, group, interval_retries_dict)
            # Remove volume(s) from the group
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

    def _remove_remote_vols_from_volume_group(
            self, array, volumes, group, extra_specs):
        """Remove the remote volumes from their volume group.

        :param array: the array serial number
        :param volumes: list of volumes
        :param group: the id of the group
        :param extra_specs: the extra specifications
        """
        remote_device_list = []
        __, remote_array = self.get_rdf_details(array)
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

    def _get_volume_device_ids(self, volumes, array):
        """Get volume device ids from volume.

        :param volumes: volume objects
        :returns: device_ids
        """
        device_ids = []
        for volume in volumes:
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
        array, interval_retries_dict = self.utils.get_volume_group_utils(
            group, self.interval, self.retries)
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
                volumes_model_update, rollback_dict, list_volume_pairs = (
                    self. _create_vol_and_add_to_group(
                        volume, group.id, tgt_name, rollback_dict,
                        source_vols, snapshots, list_volume_pairs,
                        volumes_model_update))

            snap_name, rollback_dict = (
                self._create_group_replica_and_get_snap_name(
                    group.id, actual_source_grp, source_id, source_sg,
                    rollback_dict, create_snapshot))

            # Link and break the snapshot to the source group
            self.provision.link_and_break_replica(
                array, src_grp_name, tgt_name, snap_name,
                interval_retries_dict, list_volume_pairs,
                delete_snapshot=create_snapshot)

            # Update the replication status
            if group.is_replicated:
                volumes_model_update = self._replicate_group(
                    array, volumes_model_update,
                    tgt_name, interval_retries_dict)
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
            self, volume, group_id, tgt_name, rollback_dict, source_vols,
            snapshots, list_volume_pairs, volumes_model_update):
        """Creates the volume group from source.

        :param volume: volume object
        :param group_id: the group id
        :param tgt_name: target name
        :param rollback_dict: rollback dict
        :param source_vols: source volumes
        :param snapshots: snapshot objects
        :param list_volume_pairs: volume pairs list
        :param volumes_model_update: volume model update
        :returns: volumes_model_update, rollback_dict, list_volume_pairs
        """

        src_dev_id, extra_specs, vol_size, tgt_vol_name = (
            self._get_clone_vol_info(
                volume, source_vols, snapshots))
        volume_dict = self._create_volume(
            tgt_vol_name, vol_size, extra_specs)
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
                volume, volume_dict, group_id))
        return volumes_model_update, rollback_dict, list_volume_pairs

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
                    src_dev_id, __ = self._parse_snap_info(
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
        :return: volumes_model_update
        """
        rdf_group_no, remote_array = self.get_rdf_details(array)
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
        return volumes_model_update

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

            rdf_group_no, _ = self.get_rdf_details(array)
            self.provision.enable_group_replication(
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

            rdf_group_no, _ = self.get_rdf_details(array)
            self.provision.disable_group_replication(
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
        model_update = {}
        vol_model_updates = []
        if not volumes:
            # Return if empty group
            return model_update, vol_model_updates

        try:
            extra_specs = self._initial_setup(volumes[0])
            array = ast.literal_eval(volumes[0].provider_location)['array']
            extra_specs[utils.ARRAY] = array
            if group:
                volume_group = self._find_volume_group(array, group)
                if volume_group:
                    if 'name' in volume_group:
                        vol_grp_name = volume_group['name']
                if vol_grp_name is None:
                    raise exception.GroupNotFound(group_id=group.id)

            # As we only support a single replication target, ignore
            # any secondary_backend_id which is not 'default'
            failover = False if secondary_backend_id == 'default' else True
            if not is_metro:
                rdf_group_no, _ = self.get_rdf_details(array)
                self.provision.failover_group(
                    array, vol_grp_name, rdf_group_no, extra_specs, failover)
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
                    failover, vol_grp_name, vol_rep_status, utils.REP_ASYNC)

            update = {'id': vol.id,
                      'replication_status': vol_rep_status,
                      'provider_location': loc,
                      'replication_driver_data': rep_data}
            if host:
                update = {'volume_id': vol.id, 'updates': update}
            vol_model_updates.append(update)

        LOG.debug("Volume model updates: %s", vol_model_updates)
        return model_update, vol_model_updates

    def get_attributes_from_cinder_config(self):
        """Get all attributes from the configuration file

        :returns: kwargs
        """
        kwargs = None
        username = self.configuration.safe_get(utils.VMAX_USER_NAME)
        password = self.configuration.safe_get(utils.VMAX_PASSWORD)
        if username and password:
            serial_number = self._get_configuration_value(
                utils.VMAX_ARRAY, utils.POWERMAX_ARRAY)
            if serial_number is None:
                LOG.error("Array Serial Number must be set in cinder.conf")
            srp_name = self._get_configuration_value(
                utils.VMAX_SRP, utils.POWERMAX_SRP)
            if srp_name is None:
                LOG.error("SRP Name must be set in cinder.conf")
            slo = self._get_configuration_value(
                utils.VMAX_SERVICE_LEVEL, utils.POWERMAX_SERVICE_LEVEL)
            workload = self.configuration.safe_get(utils.VMAX_WORKLOAD)
            port_groups = self._get_configuration_value(
                utils.VMAX_PORT_GROUPS, utils.POWERMAX_PORT_GROUPS)
            random_portgroup = None
            if port_groups:
                random_portgroup = random.choice(port_groups)

            kwargs = (
                {'RestServerIp': self.configuration.safe_get(
                    utils.VMAX_SERVER_IP),
                 'RestServerPort': self._get_unisphere_port(),
                 'RestUserName': username,
                 'RestPassword': password,
                 'SerialNumber': serial_number,
                 'srpName': srp_name,
                 'PortGroup': random_portgroup})

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

    def _get_configuration_value(self, first_key, second_key):
        """Get the configuration value of the first or second key

        :param first_key: the first key
        :param second_key: the second key
        :returns: value
        """
        return_value = None
        if (self.configuration.safe_get(first_key)
                and self.configuration.safe_get(second_key)):
            LOG.error("Cannot specifiy both %(first_key)s. "
                      "and %(second_key)s.",
                      {'first_key': first_key, 'second_key': second_key})
        else:
            return_value = self.configuration.safe_get(first_key)
            if return_value is None:
                return_value = self.configuration.safe_get(second_key)
        return return_value

    def _get_unlink_configuration_value(self, first_key, second_key):
        """Get the configuration value of snapvx_unlink_limit

        This will give back the value of the default snapvx_unlink_limit
        unless either powermax_snapvx_unlink_limit or vmax_snapvx_unlink_limit
        is set to something else

        :param first_key: the first key
        :param second_key: the second key
        :returns: value
        """
        return_value = self.configuration.safe_get(second_key)
        if return_value == 3:
            return_value = self.configuration.safe_get(first_key)
        return return_value

    def _get_unisphere_port(self):
        """Get unisphere port from the configuration file

        :returns: unisphere port
        """
        if self.configuration.safe_get(utils.VMAX_SERVER_PORT_OLD):
            return self.configuration.safe_get(utils.VMAX_SERVER_PORT_OLD)
        elif self.configuration.safe_get(utils.VMAX_SERVER_PORT_NEW):
            return self.configuration.safe_get(utils.VMAX_SERVER_PORT_NEW)
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
        sourcedevice_id, snap_name = self._parse_snap_info(
            array, snapshot)
        if not sourcedevice_id or not snap_name:
            LOG.error("No snapshot found on the array")
            exception_message = (_(
                "Failed to revert the volume to the snapshot"))
            raise exception.VolumeDriverException(message=exception_message)
        self._sync_check(array, sourcedevice_id, extra_specs)
        try:
            LOG.info("Reverting device: %(deviceid)s "
                     "to snapshot: %(snapname)s.",
                     {'deviceid': sourcedevice_id, 'snapname': snap_name})
            self.provision.revert_volume_snapshot(
                array, sourcedevice_id, snap_name, extra_specs)
            # Once the restore is done, we need to check if it is complete
            restore_complete = self.provision.is_restore_complete(
                array, sourcedevice_id, snap_name, extra_specs)
            if not restore_complete:
                LOG.debug("Restore couldn't complete in the specified "
                          "time interval. The terminate restore may fail")
            LOG.debug("Terminating restore session")
            # This may throw an exception if restore_complete is False
            self.provision.delete_volume_snap(
                array, snap_name, sourcedevice_id, restored=True, generation=0)
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
