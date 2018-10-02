# Copyright (c) 2017 Dell Inc. or its subsidiaries.
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
import os.path
import sys

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import strutils
import six
import uuid

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder.volume import configuration
from cinder.volume.drivers.dell_emc.vmax import masking
from cinder.volume.drivers.dell_emc.vmax import provision
from cinder.volume.drivers.dell_emc.vmax import rest
from cinder.volume.drivers.dell_emc.vmax import utils
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types
LOG = logging.getLogger(__name__)

CONF = cfg.CONF

CINDER_EMC_CONFIG_FILE = '/etc/cinder/cinder_dell_emc_config.xml'
CINDER_EMC_CONFIG_FILE_PREFIX = '/etc/cinder/cinder_dell_emc_config_'
CINDER_EMC_CONFIG_FILE_POSTFIX = '.xml'
BACKENDNAME = 'volume_backend_name'
PREFIXBACKENDNAME = 'capabilities:volume_backend_name'

# Replication
REPLICATION_DISABLED = fields.ReplicationStatus.DISABLED
REPLICATION_ENABLED = fields.ReplicationStatus.ENABLED
REPLICATION_FAILOVER = fields.ReplicationStatus.FAILED_OVER
FAILOVER_ERROR = fields.ReplicationStatus.FAILOVER_ERROR
REPLICATION_ERROR = fields.ReplicationStatus.ERROR


vmax_opts = [
    cfg.StrOpt('cinder_dell_emc_config_file',
               default=CINDER_EMC_CONFIG_FILE,
               help='Use this file for cinder emc plugin '
                    'config data.'),
    cfg.StrOpt('interval',
               default=3,
               help='Use this value to specify '
                    'length of the interval in seconds.'),
    cfg.StrOpt('retries',
               default=200,
               help='Use this value to specify '
                    'number of retries.'),
    cfg.BoolOpt('initiator_check',
                default=False,
                help='Use this value to enable '
                     'the initiator_check.')]

CONF.register_opts(vmax_opts, group=configuration.SHARED_CONF_GROUP)


class VMAXCommon(object):
    """Common class for Rest based VMAX volume drivers.

    This common class is for Dell EMC VMAX volume drivers
    based on UniSphere Rest API.
    It supports VMAX 3 and VMAX All Flash arrays.

    """
    VERSION = "3.0.0"

    stats = {'driver_version': '3.0',
             'free_capacity_gb': 0,
             'reserved_percentage': 0,
             'storage_protocol': None,
             'total_capacity_gb': 0,
             'vendor_name': 'Dell EMC',
             'volume_backend_name': None,
             'replication_enabled': False,
             'replication_targets': None}

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
        self.configuration.append_config_values(vmax_opts)
        self.rest = rest.VMAXRest()
        self.utils = utils.VMAXUtils()
        self.masking = masking.VMAXMasking(prtcl, self.rest)
        self.provision = provision.VMAXProvision(self.rest)
        self.version = version
        # replication
        self.replication_enabled = False
        self.extend_replicated_vol = False
        self.rep_devices = None
        self.active_backend_id = active_backend_id
        self.failover = False
        self._get_replication_info()
        self._gather_info()

    def _gather_info(self):
        """Gather the relevant information for update_volume_stats."""
        self._get_attributes_from_config()
        array_info = self.utils.parse_file_to_get_array_map(
            self.pool_info['config_file'])
        self.rest.set_rest_credentials(array_info)
        finalarrayinfolist = self._get_slo_workload_combinations(
            array_info)
        self.pool_info['arrays_info'] = finalarrayinfolist

    def _get_attributes_from_config(self):
        """Get relevent details from configuration file."""
        if hasattr(self.configuration, 'cinder_dell_emc_config_file'):
            self.pool_info['config_file'] = (
                self.configuration.cinder_dell_emc_config_file)
        else:
            self.pool_info['config_file'] = (
                self.configuration.safe_get('cinder_dell_emc_config_file'))
        self.interval = self.configuration.safe_get('interval')
        self.retries = self.configuration.safe_get('retries')
        self.pool_info['backend_name'] = (
            self.configuration.safe_get('volume_backend_name'))
        self.pool_info['max_over_subscription_ratio'] = (
            self.configuration.safe_get('max_over_subscription_ratio'))
        self.pool_info['reserved_percentage'] = (
            self.configuration.safe_get('reserved_percentage'))
        LOG.debug(
            "Updating volume stats on file %(emcConfigFileName)s on "
            "backend %(backendName)s.",
            {'emcConfigFileName': self.pool_info['config_file'],
             'backendName': self.pool_info['backend_name']})

    def _get_initiator_check_flag(self):
        """Reads the configuration for initator_check flag.

        :returns:  flag
        """
        conf_string = (self.configuration.safe_get('initiator_check'))
        ret_val = False
        string_true = "True"
        if conf_string:
            if conf_string.lower() == string_true.lower():
                ret_val = True
        return ret_val

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
                # use self.replication_enabled for update_volume_stats
                self.replication_enabled = True
                LOG.debug("The replication configuration is %(rep_config)s.",
                          {'rep_config': self.rep_config})
        elif self.rep_devices and len(self.rep_devices) > 1:
            LOG.error("More than one replication target is configured. "
                      "Dell EMC VMAX only suppports a single replication "
                      "target. Replication will not be enabled.")

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
            # Get the srp slo & workload settings
            slo_settings = self.rest.get_slo_list(array)
            # Remove 'None' from the list (so a 'None' slo is not combined
            # with a workload, which is not permitted)
            slo_settings = [x for x in slo_settings
                            if x.lower() not in ['none', 'optimized']]
            workload_settings = self.rest.get_workload_settings(array)
            workload_settings.append("None")
            slo_workload_set = set(
                ['%(slo)s:%(workload)s' % {'slo': slo, 'workload': workload}
                 for slo in slo_settings for workload in workload_settings])
            # Add back in in the only allowed 'None' slo/ workload combination
            slo_workload_set.add('None:None')
            slo_workload_set.add('Optimized:None')

            finalarrayinfolist = []
            for sloWorkload in slo_workload_set:
                # Doing a shallow copy will work as we are modifying
                # only strings
                temparray_info = array_info.copy()
                slo, workload = sloWorkload.split(':')
                temparray_info['SLO'] = slo
                temparray_info['Workload'] = workload
                finalarrayinfolist.append(temparray_info)
        except Exception as e:
            exception_message = (_(
                "Unable to get the SLO/Workload combinations from the array. "
                "Exception received was %(e)s") % {'e': six.text_type(e)})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                data=exception_message)
        return finalarrayinfolist

    def create_volume(self, volume):
        """Creates a EMC(VMAX) volume from a storage group.

        :param volume: volume object
        :returns:  model_update - dict
        """
        model_update = {}
        volume_id = volume.id
        extra_specs = self._initial_setup(volume)

        # Volume_name naming convention is 'OS-UUID'.
        volume_name = self.utils.get_volume_element_name(volume_id)
        volume_size = volume.size

        volume_dict = (self._create_volume(
            volume_name, volume_size, extra_specs))

        if volume.group_id is not None:
            group_name = self.provision.get_or_create_volume_group(
                extra_specs[utils.ARRAY], volume.group, extra_specs)
            self.masking.add_volume_to_storage_group(
                extra_specs[utils.ARRAY], volume_dict['device_id'],
                group_name, volume_name, extra_specs)

        # Set-up volume replication, if enabled
        if self.utils.is_replication_enabled(extra_specs):
            rep_update = self._replicate_volume(volume, volume_name,
                                                volume_dict, extra_specs)
            model_update.update(rep_update)
        LOG.info("Leaving create_volume: %(name)s. Volume dict: %(dict)s.",
                 {'name': volume_name, 'dict': volume_dict})
        model_update.update(
            {'provider_location': six.text_type(volume_dict)})
        return model_update

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        :param volume: volume object
        :param snapshot: snapshot object
        :returns: model_update
        :raises: VolumeBackendAPIException:
        """
        LOG.debug("Entering create_volume_from_snapshot.")
        model_update = {}
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
            rep_update = self._replicate_volume(volume, snapshot['name'],
                                                clone_dict, extra_specs)
            model_update.update(rep_update)

        model_update.update(
            {'provider_location': six.text_type(clone_dict)})
        return model_update

    def create_cloned_volume(self, clone_volume, source_volume):
        """Creates a clone of the specified volume.

        :param clone_volume: clone volume Object
        :param source_volume: volume object
        :returns: model_update, dict
        """
        model_update = {}
        extra_specs = self._initial_setup(clone_volume)
        clone_dict = self._create_cloned_volume(clone_volume, source_volume,
                                                extra_specs)

        # Set-up volume replication, if enabled
        if self.utils.is_replication_enabled(extra_specs):
            rep_update = self._replicate_volume(
                clone_volume, clone_volume.name, clone_dict, extra_specs)
            model_update.update(rep_update)

        model_update.update(
            {'provider_location': six.text_type(clone_dict)})
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
        :returns: replication model_update
        """
        array = volume_dict['array']
        try:
            device_id = volume_dict['device_id']
            replication_status, replication_driver_data = (
                self.setup_volume_replication(
                    array, volume, device_id, extra_specs))
        except Exception:
            if delete_src:
                self._cleanup_replication_source(
                    array, volume, volume_name, volume_dict, extra_specs)
            raise
        return ({'replication_status': replication_status,
                 'replication_driver_data': six.text_type(
                     replication_driver_data)})

    def delete_volume(self, volume):
        """Deletes a EMC(VMAX) volume.

        :param volume: volume object
        """
        LOG.info("Deleting Volume: %(volume)s",
                 {'volume': volume.name})
        volume_name = self._delete_volume(volume)
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
            @coordination.synchronized("emc-source-{sourcedevice_id}")
            def do_delete_volume_snap_check_for_links(sourcedevice_id):
                # Ensure snap has not been recently deleted
                self.provision.delete_volume_snap_check_for_links(
                    extra_specs[utils.ARRAY], snap_name,
                    sourcedevice_id, extra_specs)
            do_delete_volume_snap_check_for_links(sourcedevice_id)

            LOG.info("Leaving delete_snapshot: %(ssname)s.",
                     {'ssname': snap_name})

    def _remove_members(self, array, volume, device_id,
                        extra_specs, connector):
        """This method unmaps a volume from a host.

        Removes volume from the storage group that belongs to a masking view.
        :param array: the array serial number
        :param volume: volume object
        :param device_id: the VMAX volume device id
        :param extra_specs: extra specifications
        :param connector: the connector object
        """
        volume_name = volume.name
        LOG.debug("Detaching volume %s.", volume_name)
        return self.masking.remove_and_reset_members(
            array, volume, device_id, volume_name,
            extra_specs, True, connector)

    def _unmap_lun(self, volume, connector):
        """Unmaps a volume from the host.

        :param volume: the volume Object
        :param connector: the connector Object
        """
        extra_specs = self._initial_setup(volume)
        if self.utils.is_volume_failed_over(volume):
            extra_specs = self._get_replication_extra_specs(
                extra_specs, self.rep_config)
        volume_name = volume.name
        LOG.info("Unmap volume: %(volume)s.",
                 {'volume': volume_name})
        if connector is not None:
            host = self.utils.get_host_short_name(connector['host'])
        else:
            LOG.warning("Cannot get host name from connector object - "
                        "assuming force-detach.")
            host = None

        device_info, is_live_migration, source_storage_group_list = (
            self.find_host_lun_id(volume, host, extra_specs))
        if 'hostlunid' not in device_info:
            LOG.info("Volume %s is not mapped. No volume to unmap.",
                     volume_name)
            return
        if is_live_migration and len(source_storage_group_list) == 1:
            LOG.info("Volume %s is mapped. Failed live migration case",
                     volume_name)
            return
        source_nf_sg = None
        array = extra_specs[utils.ARRAY]
        if len(source_storage_group_list) > 1:
            for storage_group in source_storage_group_list:
                if 'NONFAST' in storage_group:
                    source_nf_sg = storage_group
                    break
        if source_nf_sg:
            # Remove volume from non fast storage group
            self.masking.remove_volume_from_sg(
                array, device_info['device_id'], volume_name, storage_group,
                extra_specs)
        else:
            self._remove_members(array, volume, device_info['device_id'],
                                 extra_specs, connector)

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
                         the EMC configuration xml file.
                         These are precreated. If the portGroup does not
                         exist then an error will be returned to the user
         maskingview_name  = OS-<shortHostName>-<srpName>-<shortProtocol>-MV
                        e.g OS-myShortHost-SRP_1-I-MV

        :param volume: volume Object
        :param connector: the connector Object
        :returns: dict -- device_info_dict - device information dict
        """
        extra_specs = self._initial_setup(volume)
        is_multipath = connector.get('multipath', False)

        volume_name = volume.name
        LOG.info("Initialize connection: %(volume)s.",
                 {'volume': volume_name})
        if self.utils.is_volume_failed_over(volume):
            extra_specs = self._get_replication_extra_specs(
                extra_specs, self.rep_config)
        device_info_dict, is_live_migration, source_storage_group_list = (
            self.find_host_lun_id(volume, connector['host'], extra_specs))
        masking_view_dict = self._populate_masking_dict(
            volume, connector, extra_specs)

        if ('hostlunid' in device_info_dict and
                device_info_dict['hostlunid'] is not None and
                is_live_migration is False) or (
                    is_live_migration and len(source_storage_group_list) > 1):
            hostlunid = device_info_dict['hostlunid']
            LOG.info("Volume %(volume)s is already mapped. "
                     "The hostlunid is  %(hostlunid)s.",
                     {'volume': volume_name,
                      'hostlunid': hostlunid})
            port_group_name = (
                self.get_port_group_from_masking_view(
                    extra_specs[utils.ARRAY],
                    device_info_dict['maskingview']))

        else:
            if is_live_migration:
                source_nf_sg, source_sg, source_parent_sg, is_source_nf_sg = (
                    self._setup_for_live_migration(
                        device_info_dict, source_storage_group_list))
                masking_view_dict['source_nf_sg'] = source_nf_sg
                masking_view_dict['source_sg'] = source_sg
                masking_view_dict['source_parent_sg'] = source_parent_sg
                try:
                    self.masking.pre_live_migration(
                        source_nf_sg, source_sg, source_parent_sg,
                        is_source_nf_sg, device_info_dict, extra_specs)
                except Exception:
                    # Move it back to original storage group
                    source_storage_group_list = (
                        self.rest.get_storage_groups_from_volume(
                            device_info_dict['array'],
                            device_info_dict['device_id']))
                    self.masking.failed_live_migration(
                        masking_view_dict, source_storage_group_list,
                        extra_specs)
                    exception_message = (_(
                        "Unable to setup live migration because of the "
                        "following error: %(errorMessage)s.")
                        % {'errorMessage': sys.exc_info()[1]})
                    raise exception.VolumeBackendAPIException(
                        data=exception_message)
            device_info_dict, port_group_name = (
                self._attach_volume(
                    volume, connector, extra_specs, masking_view_dict,
                    is_live_migration))
            if is_live_migration:
                self.masking.post_live_migration(
                    masking_view_dict, extra_specs)
        if self.protocol.lower() == 'iscsi':
            device_info_dict['ip_and_iqn'] = (
                self._find_ip_and_iqns(
                    extra_specs[utils.ARRAY], port_group_name))
            device_info_dict['is_multipath'] = is_multipath
        return device_info_dict

    def _attach_volume(self, volume, connector, extra_specs,
                       masking_view_dict, is_live_migration=False):
        """Attach a volume to a host.

        :param volume: the volume object
        :param connector: the connector object
        :param extra_specs: extra specifications
        :param masking_view_dict: masking view information
        :returns: dict -- device_info_dict
                  String -- port group name
        :raises: VolumeBackendAPIException
        """
        volume_name = volume.name
        if is_live_migration:
            masking_view_dict['isLiveMigration'] = True
        else:
            masking_view_dict['isLiveMigration'] = False
        rollback_dict = self.masking.setup_masking_view(
            masking_view_dict[utils.ARRAY], volume,
            masking_view_dict, extra_specs)

        # Find host lun id again after the volume is exported to the host.

        device_info_dict, __, __ = self.find_host_lun_id(
            volume, connector['host'], extra_specs)
        if 'hostlunid' not in device_info_dict:
            # Did not successfully attach to host,
            # so a rollback for FAST is required.
            LOG.error("Error Attaching volume %(vol)s. "
                      "Cannot retrieve hostlunid. ",
                      {'vol': volume_name})
            self.masking.check_if_rollback_action_for_masking_required(
                masking_view_dict[utils.ARRAY],
                masking_view_dict[utils.DEVICE_ID],
                rollback_dict)
            exception_message = (_("Error Attaching volume %(vol)s.")
                                 % {'vol': volume_name})
            raise exception.VolumeBackendAPIException(
                data=exception_message)

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
        device_id = self._find_device_on_array(volume, extra_specs)
        array = extra_specs[utils.ARRAY]
        # Check if volume is part of an on-going clone operation
        self._sync_check(array, device_id, volume_name, extra_specs)
        if device_id is None:
            exception_message = (_("Cannot find Volume: %(volume_name)s. "
                                   "Extend operation.  Exiting....")
                                 % {'volume_name': volume_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)
        __, snapvx_src, __ = self.rest.is_vol_in_rep_session(array, device_id)
        if snapvx_src:
            exception_message = (
                _("The volume: %(volume)s is a snapshot source. Extending a "
                  "volume with snapVx snapshots is not supported. Exiting...")
                % {'volume': volume_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        if int(original_vol_size) > int(new_size):
            exception_message = (_(
                "Your original size: %(original_vol_size)s GB is greater "
                "than: %(new_size)s GB. Only Extend is supported. Exiting...")
                % {'original_vol_size': original_vol_size,
                   'new_size': new_size})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)
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

        LOG.debug("Leaving extend_volume: %(volume_name)s. ",
                  {'volume_name': volume_name})

    def update_volume_stats(self):
        """Retrieve stats info."""
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
            self.rest.set_rest_credentials(array_info)
            if array_info['SerialNumber'] not in arrays:
                (location_info, total_capacity_gb, free_capacity_gb,
                 provisioned_capacity_gb,
                 array_reserve_percent) = self._update_srp_stats(array_info)
            else:
                already_queried = True
            pool_name = ("%(slo)s+%(workload)s+%(srpName)s+%(array)s"
                         % {'slo': array_info['SLO'],
                            'workload': array_info['Workload'],
                            'srpName': array_info['srpName'],
                            'array': array_info['SerialNumber']})

            if already_queried:
                # The dictionary will only have one key per VMAX
                # Construct the location info
                temp_location_info = (
                    ("%(arrayName)s#%(srpName)s#%(slo)s#%(workload)s"
                     % {'arrayName': array_info['SerialNumber'],
                        'srpName': array_info['srpName'],
                        'slo': array_info['SLO'],
                        'workload': array_info['Workload']}))
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
                        'replication_enabled': self.replication_enabled}
                if arrays[array_info['SerialNumber']][3]:
                    if reserved_percentage:
                        if (arrays[array_info['SerialNumber']][3] >
                                reserved_percentage):
                            pool['reserved_percentage'] = (
                                arrays[array_info['SerialNumber']][3])
                    else:
                        pool['reserved_percentage'] = (
                            arrays[array_info['SerialNumber']][3])
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
                        'replication_enabled': self.replication_enabled
                        }
                if array_reserve_percent:
                    if isinstance(reserved_percentage, int):
                        if array_reserve_percent > reserved_percentage:
                            pool['reserved_percentage'] = array_reserve_percent
                    else:
                        pool['reserved_percentage'] = array_reserve_percent

            if max_oversubscription_ratio and (
                    0.0 < max_oversubscription_ratio < 1):
                pool['max_over_subscription_ratio'] = (
                    self.utils.get_default_oversubscription_ratio(
                        max_oversubscription_ratio))
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

        location_info = ("%(arrayName)s#%(srpName)s#%(slo)s#%(workload)s"
                         % {'arrayName': array_info['SerialNumber'],
                            'srpName': array_info['srpName'],
                            'slo': array_info['SLO'],
                            'workload': array_info['Workload']})

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
        :returns: string -- configuration file
        """
        qos_specs = {}
        extra_specs = self.utils.get_volumetype_extra_specs(
            volume, volume_type_id)
        type_id = volume.volume_type_id
        if type_id:
            res = volume_types.get_volume_type_qos_specs(type_id)
            qos_specs = res['qos_specs']

        config_group = None
        # If there are no extra specs then the default case is assumed.
        if extra_specs:
            config_group = self.configuration.config_group
            if extra_specs.get('replication_enabled') == '<is> True':
                extra_specs[utils.IS_RE] = True
        config_file = self._register_config_file_from_config_group(
            config_group)
        return extra_specs, config_file, qos_specs

    def _find_device_on_array(self, volume, extra_specs):
        """Given the volume get the VMAX device Id.

        :param volume: volume object
        :param extra_specs: the extra Specs
        :returns: array, device_id
        """
        founddevice_id = None
        volume_name = volume.id

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
            element_name = self.utils.get_volume_element_name(
                volume_name)
            admin_metadata = {}
            if 'admin_metadata' in volume:
                admin_metadata = volume.admin_metadata
            if 'targetVolumeName' in admin_metadata:
                target_vol_name = admin_metadata['targetVolumeName']
                founddevice_id = self.rest.check_volume_device_id(
                    array, target_vol_name, device_id)
            else:
                founddevice_id = self.rest.check_volume_device_id(
                    array, device_id, element_name)

        if founddevice_id is None:
            LOG.debug("Volume %(volume_name)s not found on the array.",
                      {'volume_name': volume_name})
        else:
            LOG.debug("Volume name: %(volume_name)s  Volume device id: "
                      "%(founddevice_id)s.",
                      {'volume_name': volume_name,
                       'founddevice_id': founddevice_id})

        return founddevice_id

    def find_host_lun_id(self, volume, host, extra_specs):
        """Given the volume dict find the host lun id for a volume.

        :param volume: the volume dict
        :param host: host from connector (can be None on a force-detach)
        :param extra_specs: the extra specs
        :returns: dict -- the data dict
        """
        maskedvols = {}
        is_live_migration = False
        volume_name = volume.name
        device_id = self._find_device_on_array(volume, extra_specs)
        host_name = self.utils.get_host_short_name(host) if host else None
        if device_id:
            array = extra_specs[utils.ARRAY]
            source_storage_group_list = (
                self.rest.get_storage_groups_from_volume(array, device_id))
            # return only masking views for this host
            maskingviews = self.get_masking_views_from_volume(
                array, device_id, host_name, source_storage_group_list)

            for maskingview in maskingviews:
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
                    "with the device id: %(device_id)s.",
                    {'volume_name': volume_name,
                     'device_id': device_id})
            else:
                LOG.debug("Device info: %(maskedvols)s.",
                          {'maskedvols': maskedvols})
                if host:
                    hoststr = ("-%(host)s-" % {'host': host_name})

                    if (hoststr.lower()
                            not in maskedvols['maskingview'].lower()):
                        LOG.debug("Volume is masked but not to host %(host)s "
                                  "as is expected. Assuming live migration.",
                                  {'host': host})
                        is_live_migration = True
                    else:
                        for storage_group in source_storage_group_list:
                            if 'NONFAST' in storage_group:
                                is_live_migration = True
                                break
        else:
            exception_message = (_("Cannot retrieve volume %(vol)s "
                                   "from the array.") % {'vol': volume_name})
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(exception_message)

        return maskedvols, is_live_migration, source_storage_group_list

    def get_masking_views_from_volume(self, array, device_id, host,
                                      storage_group_list=None):
        """Retrieve masking view list for a volume.

        :param array: array serial number
        :param device_id: the volume device id
        :param host: the host
        :param storage_group_list: the storage group list to use
        :returns: masking view list
        """
        LOG.debug("Getting masking views from volume")
        maskingview_list = []
        host_compare = False
        if not storage_group_list:
            storage_group_list = self.rest.get_storage_groups_from_volume(
                array, device_id)
            host_compare = True if host else False
        for sg in storage_group_list:
            mvs = self.rest.get_masking_views_from_storage_group(
                array, sg)
            for mv in mvs:
                if host_compare:
                    if host.lower() in mv.lower():
                        maskingview_list.append(mv)
                else:
                    maskingview_list.append(mv)
        return maskingview_list

    def _register_config_file_from_config_group(self, config_group_name):
        """Given the config group name register the file.

        :param config_group_name: the config group name
        :returns: string -- configurationFile - name of the configuration file
        :raises: VolumeBackendAPIException:
        """
        if config_group_name is None:
            return CINDER_EMC_CONFIG_FILE
        if hasattr(self.configuration, 'cinder_dell_emc_config_file'):
            config_file = self.configuration.cinder_dell_emc_config_file
        else:
            config_file = (
                ("%(prefix)s%(configGroupName)s%(postfix)s"
                 % {'prefix': CINDER_EMC_CONFIG_FILE_PREFIX,
                    'configGroupName': config_group_name,
                    'postfix': CINDER_EMC_CONFIG_FILE_POSTFIX}))

        # The file saved in self.configuration may not be the correct one,
        # double check.
        if config_group_name not in config_file:
            config_file = (
                ("%(prefix)s%(configGroupName)s%(postfix)s"
                 % {'prefix': CINDER_EMC_CONFIG_FILE_PREFIX,
                    'configGroupName': config_group_name,
                    'postfix': CINDER_EMC_CONFIG_FILE_POSTFIX}))

        if os.path.isfile(config_file):
            LOG.debug("Configuration file : %(configurationFile)s exists.",
                      {'configurationFile': config_file})
        else:
            exception_message = (_(
                "Configuration file %(configurationFile)s does not exist.")
                % {'configurationFile': config_file})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        return config_file

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
            extra_specs, config_file, qos_specs = (
                self._set_config_file_and_get_extra_specs(
                    volume, volume_type_id))
            array_info = self.utils.parse_file_to_get_array_map(
                config_file)
            if not array_info:
                exception_message = (_(
                    "Unable to get corresponding record for srp."))
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

            self.rest.set_rest_credentials(array_info)

            extra_specs = self._set_vmax_extra_specs(extra_specs, array_info)
            if qos_specs and qos_specs.get('consumer') != "front-end":
                extra_specs['qos'] = qos_specs.get('specs')
        except Exception:
            exception_message = (_(
                "Unable to get configuration information necessary to "
                "create a volume: %(errorMessage)s.")
                % {'errorMessage': sys.exc_info()[1]})
            raise exception.VolumeBackendAPIException(data=exception_message)
        return extra_specs

    def _populate_masking_dict(self, volume, connector, extra_specs):
        """Get all the names of the maskingview and sub-components.

        :param volume: the volume object
        :param connector: the connector object
        :param extra_specs: extra specifications
        :returns: dict -- a dictionary with masking view information
        """
        masking_view_dict = {}
        host_name = connector['host']
        unique_name = self.utils.truncate_string(extra_specs[utils.SRP], 12)
        protocol = self.utils.get_short_protocol_type(self.protocol)
        short_host_name = self.utils.get_host_short_name(host_name)
        masking_view_dict[utils.DISABLECOMPRESSION] = False
        masking_view_dict['replication_enabled'] = False
        slo = extra_specs[utils.SLO]
        workload = extra_specs[utils.WORKLOAD]
        rep_enabled = self.utils.is_replication_enabled(extra_specs)
        short_pg_name = self.utils.get_pg_short_name(
            extra_specs[utils.PORTGROUPNAME])
        masking_view_dict[utils.SLO] = slo
        masking_view_dict[utils.WORKLOAD] = workload
        masking_view_dict[utils.SRP] = unique_name
        masking_view_dict[utils.ARRAY] = extra_specs[utils.ARRAY]
        masking_view_dict[utils.PORTGROUPNAME] = (
            extra_specs[utils.PORTGROUPNAME])
        if self._get_initiator_check_flag():
            masking_view_dict[utils.INITIATOR_CHECK] = True
        else:
            masking_view_dict[utils.INITIATOR_CHECK] = False

        if slo:
            slo_wl_combo = self.utils.truncate_string(slo + workload, 10)
            child_sg_name = (
                "OS-%(shortHostName)s-%(srpName)s-%(combo)s-%(pg)s"
                % {'shortHostName': short_host_name,
                   'srpName': unique_name,
                   'combo': slo_wl_combo,
                   'pg': short_pg_name})
            do_disable_compression = self.utils.is_compression_disabled(
                extra_specs)
            if do_disable_compression:
                child_sg_name = ("%(child_sg_name)s-CD"
                                 % {'child_sg_name': child_sg_name})
                masking_view_dict[utils.DISABLECOMPRESSION] = True
        else:
            child_sg_name = (
                "OS-%(shortHostName)s-No_SLO-%(pg)s"
                % {'shortHostName': short_host_name,
                   'pg': short_pg_name})
        if rep_enabled:
            child_sg_name += "-RE"
            masking_view_dict['replication_enabled'] = True
        mv_prefix = (
            "OS-%(shortHostName)s-%(protocol)s-%(pg)s"
            % {'shortHostName': short_host_name,
               'protocol': protocol, 'pg': short_pg_name})

        masking_view_dict[utils.SG_NAME] = child_sg_name

        masking_view_dict[utils.MV_NAME] = ("%(prefix)s-MV"
                                            % {'prefix': mv_prefix})

        masking_view_dict[utils.PARENT_SG_NAME] = ("%(prefix)s-SG"
                                                   % {'prefix': mv_prefix})
        volume_name = volume.name
        device_id = self._find_device_on_array(volume, extra_specs)
        if not device_id:
            exception_message = (_("Cannot retrieve volume %(vol)s "
                                   "from the array. ") % {'vol': volume_name})
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(exception_message)

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
            raise exception.VolumeBackendAPIException(data=exception_message)

        # Check if source is currently a snap target. Wait for sync if true.
        self._sync_check(array, source_device_id, source_volume.name,
                         extra_specs, tgt_only=True)

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
            raise exception.VolumeBackendAPIException(data=exception_message)
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
        # Check if volume is snap source
        self._sync_check(array, device_id, volume_name, extra_specs)
        # Remove from any storage groups and cleanup replication
        self._remove_vol_and_cleanup_replication(
            array, device_id, volume_name, extra_specs, volume)
        self._delete_from_srp(
            array, device_id, volume_name, extra_specs)
        return volume_name

    def _create_volume(
            self, volume_name, volume_size, extra_specs):
        """Create a volume.

        :param volume_name: the volume name
        :param volume_size: the volume size
        :param extra_specs: extra specifications
        :returns: int -- return code
        :returns: dict -- volume_dict
        :raises: VolumeBackendAPIException:
        """
        array = extra_specs[utils.ARRAY]
        is_valid_slo, is_valid_workload = self.provision.verify_slo_workload(
            array, extra_specs[utils.SLO],
            extra_specs[utils.WORKLOAD], extra_specs[utils.SRP])

        if not is_valid_slo or not is_valid_workload:
            exception_message = (_(
                "Either SLO: %(slo)s or workload %(workload)s is invalid. "
                "Examine previous error statement for valid values.")
                % {'slo': extra_specs[utils.SLO],
                   'workload': extra_specs[utils.WORKLOAD]})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        LOG.debug("Create Volume: %(volume)s  Srp: %(srp)s "
                  "Array: %(array)s "
                  "Size: %(size)lu.",
                  {'volume': volume_name,
                   'srp': extra_specs[utils.SRP],
                   'array': array,
                   'size': volume_size})

        do_disable_compression = self.utils.is_compression_disabled(
            extra_specs)

        storagegroup_name = self.masking.get_or_create_default_storage_group(
            array, extra_specs[utils.SRP], extra_specs[utils.SLO],
            extra_specs[utils.WORKLOAD], extra_specs,
            do_disable_compression)
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
        """Set the VMAX extra specs.

        The pool_name extra spec must be set, otherwise a default slo/workload
        will be chosen. The portgroup can either be passed as an extra spec
        on the volume type (e.g. 'storagetype:portgroupname = os-pg1-pg'), or
        can be chosen from a list provided in the xml file, e.g.:
        <PortGroups>
            <PortGroup>OS-PORTGROUP1-PG</PortGroup>
            <PortGroup>OS-PORTGROUP2-PG</PortGroup>
        </PortGroups>.

        :param extra_specs: extra specifications
        :param pool_record: pool record
        :returns: dict -- the extra specifications dictionary
        """
        # set extra_specs from pool_record
        extra_specs[utils.SRP] = pool_record['srpName']
        extra_specs[utils.ARRAY] = pool_record['SerialNumber']
        if not extra_specs.get(utils.PORTGROUPNAME):
            extra_specs[utils.PORTGROUPNAME] = pool_record['PortGroup']
        if not extra_specs[utils.PORTGROUPNAME]:
            error_message = (_("Port group name has not been provided - "
                               "please configure the "
                               "'storagetype:portgroupname' extra spec on "
                               "the volume type, or enter a list of "
                               "portgroups to the xml file associated with "
                               "this backend e.g."
                               "<PortGroups>"
                               "    <PortGroup>OS-PORTGROUP1-PG</PortGroup>"
                               "    <PortGroup>OS-PORTGROUP2-PG</PortGroup>"
                               "</PortGroups>."))
            LOG.exception(error_message)
            raise exception.VolumeBackendAPIException(data=error_message)

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
            if workload_from_extra_spec == pool_record['srpName']:
                workload_from_extra_spec = 'NONE'

        elif pool_record.get('ServiceLevel'):
            slo_from_extra_spec = pool_record['ServiceLevel']
            workload_from_extra_spec = pool_record.get('Workload', 'None')
            LOG.info("Pool_name is not present in the extra_specs "
                     "- using slo/ workload from xml file: %(slo)s/%(wl)s.",
                     {'slo': slo_from_extra_spec,
                      'wl': workload_from_extra_spec})

        else:
            slo_list = self.rest.get_slo_list(pool_record['SerialNumber'])
            if 'Optimized' in slo_list:
                slo_from_extra_spec = 'Optimized'
            elif 'Diamond' in slo_list:
                slo_from_extra_spec = 'Diamond'
            else:
                slo_from_extra_spec = 'None'
            workload_from_extra_spec = 'NONE'
            LOG.warning("Pool_name is not present in the extra_specs"
                        "and no slo/ workload information is present "
                        "in the xml file - using default slo/ workload "
                        "combination: %(slo)s/%(wl)s.",
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
            LOG.exception(error_message)
            raise exception.VolumeBackendAPIException(data=error_message)

    def _remove_vol_and_cleanup_replication(
            self, array, device_id, volume_name, extra_specs, volume):
        """Remove a volume from its storage groups and cleanup replication.

        :param array: the array serial number
        :param device_id: the device id
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        :param volume: the volume object
        """
        # Remove from any storage groups
        self.masking.remove_and_reset_members(
            array, volume, device_id, volume_name, extra_specs, False)
        # Cleanup remote replication
        if self.utils.is_replication_enabled(extra_specs):
            self.cleanup_lun_replication(volume, volume_name,
                                         device_id, extra_specs)

    def get_target_wwns_from_masking_view(
            self, volume, connector):
        """Find target WWNs via the masking view.

        :param volume: volume to be attached
        :param connector: the connector dict
        :returns: list -- the target WWN list
        """
        target_wwns = []
        host = connector['host']
        short_host_name = self.utils.get_host_short_name(host)
        extra_specs = self._initial_setup(volume)
        if self.utils.is_volume_failed_over(volume):
            extra_specs = self._get_replication_extra_specs(
                extra_specs, self.rep_config)
        array = extra_specs[utils.ARRAY]
        device_id = self._find_device_on_array(volume, extra_specs)
        masking_view_list = self.get_masking_views_from_volume(
            array, device_id, short_host_name)
        if masking_view_list is not None:
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
        # VMAX supports using a target volume that is bigger than
        # the source volume, so we create the target volume the desired
        # size at this point to avoid having to extend later
        try:
            clone_dict = self._create_volume(
                clone_name, clone_volume.size, extra_specs)
            target_device_id = clone_dict['device_id']
            LOG.info("The target device id is: %(device_id)s.",
                     {'device_id': target_device_id})
            if not snap_name:
                snap_name = self.utils.get_temp_snap_name(
                    clone_name, source_device_id)
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
        return clone_dict

    def _cleanup_target(
            self, array, target_device_id, source_device_id,
            clone_name, snap_name, extra_specs):
        """Cleanup target volume on failed clone/ snapshot creation.

        :param array: the array serial number
        :param target_device_id: the target device ID
        :param source_device_id: the source device ID
        :param clone_name: the name of the clone volume
        :param extra_specs: the extra specifications
        """
        snap_session = self.rest.get_sync_session(
            array, source_device_id, snap_name, target_device_id)
        if snap_session:
            self.provision.break_replication_relationship(
                array, target_device_id, source_device_id,
                snap_name, extra_specs)
        self._delete_from_srp(
            array, target_device_id, clone_name, extra_specs)

    def _sync_check(self, array, device_id, volume_name, extra_specs,
                    tgt_only=False):
        """Check if volume is part of a SnapVx sync process.

        :param array: the array serial number
        :param device_id: volume instance
        :param volume_name: volume name
        :param tgt_only: Flag - return only sessions where device is target
        :param extra_specs: extra specifications
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
                for session in snap_vx_sessions:
                    source = session['source_vol']
                    snap_name = session['snap_name']
                    targets = session['target_vol_list']
                    for target in targets:
                        # Break the replication relationship
                        LOG.debug("Unlinking source from target. Source: "
                                  "%(volume)s, Target: %(target)s.",
                                  {'volume': volume_name, 'target': target})
                        self.provision.break_replication_relationship(
                            array, target, source, snap_name, extra_specs)
                    # The snapshot name will only have 'temp' (or EMC_SMI for
                    # legacy volumes) if it is a temporary volume.
                    # Only then is it a candidate for deletion.
                    if 'temp' in snap_name or 'EMC_SMI' in snap_name:
                        @coordination.synchronized("emc-source-{source}")
                        def do_delete_temp_volume_snap(source):
                            self.provision.delete_temp_volume_snap(
                                array, snap_name, source)
                        do_delete_temp_volume_snap(source)

    def manage_existing(self, volume, external_ref):
        """Manages an existing VMAX Volume (import to Cinder).

        Renames the existing volume to match the expected name for the volume.
        Also need to consider things like QoS, Emulation, account/tenant.
        :param volume: the volume object including the volume_type_id
        :param external_ref: reference to the existing volume
        :returns: dict -- model_update
        """
        LOG.info("Beginning manage existing volume process")
        array, device_id = self.utils.get_array_and_device_id(
            volume, external_ref)
        volume_id = volume.id
        # Check if the existing volume is valid for cinder management
        self._check_lun_valid_for_cinder_management(
            array, device_id, volume_id, external_ref)
        extra_specs = self._initial_setup(volume)

        volume_name = self.utils.get_volume_element_name(volume_id)
        # Rename the volume
        LOG.debug("Rename volume %(vol)s to %(element_name)s.",
                  {'vol': volume_id,
                   'element_name': volume_name})
        self.rest.rename_volume(array, device_id, volume_name)
        provider_location = {'device_id': device_id, 'array': array}
        model_update = {'provider_location': six.text_type(provider_location)}

        # Set-up volume replication, if enabled
        if self.utils.is_replication_enabled(extra_specs):
            rep_update = self._replicate_volume(volume, volume_name,
                                                provider_location,
                                                extra_specs, delete_src=False)
            model_update.update(rep_update)

        else:
            # Add volume to default storage group
            self.masking.add_volume_to_default_storage_group(
                array, device_id, volume_name, extra_specs)

        return model_update

    def _check_lun_valid_for_cinder_management(
            self, array, device_id, volume_id, external_ref):
        """Check if a volume is valid for cinder management.

        :param array: the array serial number
        :param device_id: the device id
        :param volume_id: the cinder volume id
        :param external_ref: the external reference
        :raises: ManageExistingInvalidReference, ManageExistingAlreadyManaged:
        """
        # Ensure the volume exists on the array
        volume_details = self.rest.get_volume(array, device_id)
        if not volume_details:
            msg = (_('Unable to retrieve volume details from array for '
                     'device %(device_id)s') % {'device_id': device_id})
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)

        # Check if volume is already cinder managed
        if volume_details.get('volume_identifier'):
            volume_identifier = volume_details['volume_identifier']
            if volume_identifier.startswith(utils.VOLUME_ELEMENT_NAME_PREFIX):
                raise exception.ManageExistingAlreadyManaged(
                    volume_ref=volume_id)

        # Check if the volume is attached by checking if in any masking view.
        storagegrouplist = self.rest.get_storage_groups_from_volume(
            array, device_id)
        for sg in storagegrouplist:
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
        snapvx_tgt, snapvx_src, rdf = self.rest.is_vol_in_rep_session(
            array, device_id)
        if snapvx_tgt or snapvx_src or rdf:
            msg = (_("Unable to import volume %(device_id)s to cinder. "
                     "It is part of a replication session.")
                   % {'device_id': device_id})
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)

    def manage_existing_get_size(self, volume, external_ref):
        """Return size of an existing VMAX volume to manage_existing.

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
                _("Cannot manage existing VMAX volume %(device_id)s "
                  "- it has a size of %(vol_size)s but only whole GB "
                  "sizes are supported. Please extend the "
                  "volume to the nearest GB value before importing.")
                % {'device_id': device_id, 'vol_size': size, })
            LOG.exception(exception_message)
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=exception_message)

        LOG.debug("Size of volume %(device_id)s is %(vol_size)s GB.",
                  {'device_id': device_id, 'vol_size': int(size)})
        return int(size)

    def unmanage(self, volume):
        """Export VMAX volume from Cinder.

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
            self._sync_check(extra_specs['array'], device_id,
                             volume_name, extra_specs)
            # Remove volume from any openstack storage groups
            # and remove any replication
            self._remove_vol_and_cleanup_replication(
                extra_specs['array'], device_id,
                volume_name, extra_specs, volume)
            # Rename the volume to volumeId, thus remove the 'OS-' prefix.
            self.rest.rename_volume(
                extra_specs[utils.ARRAY], device_id, volume_id)

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

        # If the volume is attached, we can't support retype.
        # Need to explicitly check this after the code change,
        # as 'move' functionality will cause the volume to appear
        # as successfully retyped, but will remove it from the masking view.
        if volume.attach_status == 'attached':
            LOG.error(
                "Volume %(name)s is not suitable for storage "
                "assisted migration using retype "
                "as it is attached.",
                {'name': volume_name})
            return False

        if self.utils.is_replication_enabled(extra_specs):
            LOG.error("Volume %(name)s is replicated - "
                      "Replicated volumes are not eligible for "
                      "storage assisted retype. Host assisted "
                      "retype is supported.",
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
        is_compression_disabled = self.utils.is_compression_disabled(
            extra_specs)
        # Check if old type and new type have different compression types
        do_change_compression = (self.utils.change_compression_type(
            is_compression_disabled, new_type))
        is_valid, target_slo, target_workload = (
            self._is_valid_for_storage_assisted_migration(
                device_id, host, extra_specs[utils.ARRAY],
                extra_specs[utils.SRP], volume_name,
                do_change_compression))

        if not is_valid:
            LOG.error(
                "Volume %(name)s is not suitable for storage "
                "assisted migration using retype.",
                {'name': volume_name})
            return False
        if volume.host != host['host'] or do_change_compression:
            LOG.debug(
                "Retype Volume %(name)s from source host %(sourceHost)s "
                "to target host %(targetHost)s. Compression change is %(cc)r.",
                {'name': volume_name,
                 'sourceHost': volume.host,
                 'targetHost': host['host'],
                 'cc': do_change_compression})
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
        target_extra_specs = new_type['extra_specs']
        target_extra_specs[utils.SRP] = srp
        target_extra_specs[utils.ARRAY] = array
        target_extra_specs[utils.SLO] = target_slo
        target_extra_specs[utils.WORKLOAD] = target_workload
        target_extra_specs[utils.INTERVAL] = extra_specs[utils.INTERVAL]
        target_extra_specs[utils.RETRIES] = extra_specs[utils.RETRIES]
        is_compression_disabled = self.utils.is_compression_disabled(
            target_extra_specs)

        try:
            target_sg_name = self.masking.get_or_create_default_storage_group(
                array, srp, target_slo, target_workload, extra_specs,
                is_compression_disabled)
        except Exception as e:
            LOG.error("Failed to get or create storage group. "
                      "Exception received was %(e)s.", {'e': e})
            return False

        storagegroups = self.rest.get_storage_groups_from_volume(
            array, device_id)
        if not storagegroups:
            LOG.warning("Volume : %(volume_name)s does not currently "
                        "belong to any storage groups.",
                        {'volume_name': volume_name})
            self.masking.add_volume_to_storage_group(
                array, device_id, target_sg_name, volume_name, extra_specs)
        else:
            self.masking.remove_and_reset_members(
                array, volume, device_id, volume_name, target_extra_specs,
                reset=True)

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

    def _is_valid_for_storage_assisted_migration(
            self, device_id, host, source_array,
            source_srp, volume_name, do_change_compression):
        """Check if volume is suitable for storage assisted (pool) migration.

        :param device_id: the volume device id
        :param host: the host dict
        :param source_array: the volume's current array serial number
        :param source_srp: the volume's current pool name
        :param volume_name: the name of the volume to be migrated
        :param do_change_compression: do change compression
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
            target_slo = pool_details[0]
            target_workload = pool_details[1]
            target_srp = pool_details[2]
            target_array_serial = pool_details[3]
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
                    # Check if migration is from compression to non compression
                    # or vice versa
                    if not do_change_compression:
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
        """
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

        LOG.info('Successfully setup replication for %s.',
                 target_name)
        replication_status = REPLICATION_ENABLED
        replication_driver_data = rdf_dict

        return replication_status, replication_driver_data

    def cleanup_lun_replication(self, volume, volume_name,
                                device_id, extra_specs):
        """Cleanup target volume on delete.

        Extra logic if target is last in group.
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
                    self.masking.remove_and_reset_members(
                        remote_array, volume, target_device, volume_name,
                        rep_extra_specs, False)
                    self._cleanup_remote_target(
                        array, remote_array, device_id, target_device,
                        rdf_group_no, volume_name, rep_extra_specs)
                    LOG.info('Successfully destroyed replication for '
                             'volume: %(volume)s',
                             {'volume': volume_name})
                else:
                    LOG.warning('Replication target not found for '
                                'replication-enabled volume: %(volume)s',
                                {'volume': volume_name})
        except Exception as e:
            exception_message = (
                _('Cannot get necessary information to cleanup '
                  'replication target for volume: %(volume)s. '
                  'The exception received was: %(e)s. Manual '
                  'clean-up may be required. Please contact '
                  'your administrator.')
                % {'volume': volume_name, 'e': six.text_type(e)})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

    def _cleanup_remote_target(
            self, array, remote_array, device_id, target_device,
            rdf_group, volume_name, rep_extra_specs):
        """Clean-up remote replication target after exception or on deletion.

        :param array: the array serial number
        :param remote_array: the remote array serial number
        :param device_id: the source device id
        :param target_device: the target device id
        :param rdf_group: the RDF group
        :param volume_name: the volume name
        :param rep_extra_specs: replication extra specifications
        """
        are_vols_paired, local_vol_state, pair_state = (
            self.rest.are_vols_rdf_paired(
                array, remote_array, device_id, target_device, rdf_group))
        if are_vols_paired:
            # Break the sync relationship.
            self.provision.break_rdf_relationship(
                array, device_id, target_device, rdf_group,
                rep_extra_specs, pair_state)
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
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

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
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(
                data=exception_message)

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
        """
        volume_update_list = []
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
                raise exception.VolumeBackendAPIException(
                    data=exception_message)
        else:
            if self.failover:
                self.failover = False
                secondary_id = None
            else:
                exception_message = (_(
                    "Cannot failback backend %(backend)s- backend not "
                    "in failed over state. If you meant to failover, please "
                    "omit the '--backend_id default' from the command")
                    % {'backend': self.configuration.safe_get(
                       'volume_backend_name')})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        for volume in volumes:
            extra_specs = self._initial_setup(volume)
            if self.utils.is_replication_enabled(extra_specs):
                model_update = self._failover_volume(
                    volume, self.failover, extra_specs)
                volume_update_list.append(model_update)
            else:
                if self.failover:
                    # Since the array has been failed-over,
                    # volumes without replication should be in error.
                    volume_update_list.append({
                        'volume_id': volume.id,
                        'updates': {'status': 'error'}})
                else:
                    # This is a failback, so we will attempt
                    # to recover non-failed over volumes
                    recovery = self.recover_volumes_on_failback(
                        volume, extra_specs)
                    volume_update_list.append(recovery)

        LOG.info("Failover host complete.")
        return secondary_id, volume_update_list, []

    def _failover_volume(self, vol, failover, extra_specs):
        """Failover a volume.

        :param vol: the volume object
        :param failover: flag to indicate failover or failback -- bool
        :param extra_specs: the extra specifications
        :returns: model_update -- dict
        """
        loc = vol.provider_location
        rep_data = vol.replication_driver_data
        try:
            name = ast.literal_eval(loc)
            replication_keybindings = ast.literal_eval(rep_data)
            try:
                array = name['array']
            except KeyError:
                array = (name['keybindings']
                         ['SystemName'].split('+')[1].strip('-'))
            device_id = self._find_device_on_array(vol, {utils.ARRAY: array})

            (target_device, remote_array, rdf_group,
             local_vol_state, pair_state) = (
                self.get_remote_target_device(array, vol, device_id))

            self._sync_check(array, device_id, vol.name, extra_specs)
            self.provision.failover_volume(
                array, device_id, rdf_group, extra_specs,
                local_vol_state, failover)

            if failover:
                new_status = REPLICATION_FAILOVER
            else:
                new_status = REPLICATION_ENABLED

            # Transfer ownership to secondary_backend_id and
            # update provider_location field
            loc = six.text_type(replication_keybindings)
            rep_data = six.text_type(name)

        except Exception as ex:
            msg = ('Failed to failover volume %(volume_id)s. '
                   'Error: %(error)s.')
            LOG.error(msg, {'volume_id': vol.id,
                            'error': ex}, )
            new_status = FAILOVER_ERROR

        model_update = {'volume_id': vol.id,
                        'updates':
                            {'replication_status': new_status,
                             'replication_driver_data': rep_data,
                             'provider_location': loc}}
        return model_update

    def recover_volumes_on_failback(self, volume, extra_specs):
        """Recover volumes on failback.

        On failback, attempt to recover non RE(replication enabled)
        volumes from primary array.
        :param volume: the volume object
        :param extra_specs: the extra specifications
        :returns: volume_update
        """
        # Check if volume still exists on the primary
        volume_update = {'volume_id': volume.id}
        device_id = self._find_device_on_array(volume, extra_specs)
        if not device_id:
            volume_update['updates'] = {'status': 'error'}
        else:
            try:
                maskingview = self.get_masking_views_from_volume(
                    extra_specs[utils.ARRAY], device_id, '')
            except Exception:
                maskingview = None
                LOG.debug("Unable to determine if volume is in masking view.")
            if not maskingview:
                volume_update['updates'] = {'status': 'available'}
            else:
                volume_update['updates'] = {'status': 'in-use'}
        return volume_update

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
                        array, remote_array, device_id,
                        target_device, rdf_group))
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

        Cannot extend volumes in a synchronization pair. Must first break the
        relationship, extend them separately, then recreate the pair
        :param array: the array serial number
        :param volume: the volume objcet
        :param device_id: the volume device id
        :param volume_name: the volume name
        :param new_size: the new size the volume should be
        :param extra_specs: extra specifications
        """
        if self.extend_replicated_vol is True:
            try:
                (target_device, remote_array, rdf_group,
                 local_vol_state, pair_state) = (
                    self.get_remote_target_device(array, volume, device_id))

                # Volume must be removed from replication (storage) group
                # before the replication relationship can be ended (cannot
                # have a mix of replicated and non-replicated volumes as
                # the SRDF groups become unmanageable).
                self.masking.remove_and_reset_members(
                    array, volume, device_id, volume_name, extra_specs, False)

                # Repeat on target side
                rep_extra_specs = self._get_replication_extra_specs(
                    extra_specs, self.rep_config)
                self.masking.remove_and_reset_members(
                    remote_array, volume, target_device, volume_name,
                    rep_extra_specs, False)

                LOG.info("Breaking replication relationship...")
                self.provision.break_rdf_relationship(
                    array, device_id, target_device,
                    rdf_group, rep_extra_specs, pair_state)

                # Extend the source volume
                LOG.info("Extending source volume...")
                self.provision.extend_volume(
                    array, device_id, new_size, extra_specs)

                # Extend the target volume
                LOG.info("Extending target volume...")
                self.provision.extend_volume(
                    remote_array, target_device, new_size, rep_extra_specs)

                # Re-create replication relationship
                LOG.info("Recreating replication relationship...")
                self.setup_volume_replication(
                    array, volume, device_id, extra_specs, target_device)

            except Exception as e:
                exception_message = (_("Error extending volume. "
                                       "Error received was %(e)s") %
                                     {'e': e})
                LOG.exception(exception_message)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        else:
            exception_message = (_(
                "Extending a replicated volume is not "
                "permitted on this backend. Please contact "
                "your administrator."))
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

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

            # Establish replication relationship
            rdf_dict = self.rest.create_rdf_device_pair(
                array, device_id, rdf_group_no, target_device, remote_array,
                target_name, extra_specs)

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
            self.masking.remove_and_reset_members(
                remote_array, volume, target_device, target_name,
                rep_extra_specs, False)
            self._cleanup_remote_target(
                array, remote_array, device_id, target_device,
                rdf_group_no, target_name, rep_extra_specs)
            # Re-throw the exception.
            exception_message = (_("Remote replication failed with exception:"
                                   " %(e)s")
                                 % {'e': six.text_type(e)})
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        return rdf_dict

    def add_volume_to_replication_group(
            self, array, device_id, volume_name, extra_specs):
        """Add a volume to the default replication group.

        Replication groups are VMAX storage groups that contain only
        RDF-paired volumes. We can use our normal storage group operations.
        :param array: array serial number
        :param device_id: the device id
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        :returns: storagegroup_name
        """
        do_disable_compression = self.utils.is_compression_disabled(
            extra_specs)
        try:
            storagegroup_name = (
                self.masking.get_or_create_default_storage_group(
                    array, extra_specs[utils.SRP], extra_specs[utils.SLO],
                    extra_specs[utils.WORKLOAD], extra_specs,
                    do_disable_compression, is_re=True))
        except Exception as e:
            exception_message = (_("Failed to get or create replication"
                                   "group. Exception received: %(e)s")
                                 % {'e': six.text_type(e)})
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(
                data=exception_message)

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
            is_valid_slo, is_valid_workload = (
                self.provision.verify_slo_workload(
                    rep_extra_specs[utils.ARRAY],
                    extra_specs[utils.SLO],
                    rep_extra_specs[utils.WORKLOAD],
                    rep_extra_specs[utils.SRP]))
            if not is_valid_slo or not is_valid_workload:
                LOG.warning("The target array does not support the storage "
                            "pool setting for SLO %(slo)s or workload "
                            "%(workload)s. Not assigning any SLO or "
                            "workload.",
                            {'slo': extra_specs[utils.SLO],
                             'workload': extra_specs[utils.WORKLOAD]})
                rep_extra_specs[utils.SLO] = None
                if extra_specs[utils.WORKLOAD]:
                    rep_extra_specs[utils.WORKLOAD] = None

        return rep_extra_specs

    def get_secondary_stats_info(self, rep_config, array_info):
        """On failover, report on secondary array statistics.

        :param rep_config: the replication configuration
        :param array_info: the array info
        :returns: secondary_info - dict
        """
        secondary_info = array_info.copy()
        secondary_info['SerialNumber'] = six.text_type(rep_config['array'])
        secondary_info['srpName'] = rep_config['srp']
        return secondary_info

    def _setup_for_live_migration(self, device_info_dict,
                                  source_storage_group_list):
        """Function to set attributes for live migration.

        :param device_info_dict: the data dict
        :param source_storage_group_list:
        :returns: source_nf_sg: The non fast storage group
        :returns: source_sg: The source storage group
        :returns: source_parent_sg: The parent storage group
        :returns: is_source_nf_sg:if the non fast storage group already exists
        """
        array = device_info_dict['array']
        source_sg = None
        is_source_nf_sg = False
        # Get parent storage group
        source_parent_sg = self.rest.get_element_from_masking_view(
            array, device_info_dict['maskingview'], storagegroup=True)
        source_nf_sg = source_parent_sg[:-2] + 'NONFAST'
        for sg in source_storage_group_list:
            is_descendant = self.rest.is_child_sg_in_parent_sg(
                array, sg, source_parent_sg)
            if is_descendant:
                source_sg = sg
        is_descendant = self.rest.is_child_sg_in_parent_sg(
            array, source_nf_sg, source_parent_sg)
        if is_descendant:
            is_source_nf_sg = True
        return source_nf_sg, source_sg, source_parent_sg, is_source_nf_sg

    def create_group(self, context, group):
        """Creates a generic volume group.

        :param context: the context
        :param group: the group object to be created
        :returns: dict -- modelUpdate = {'status': 'available'}
        :raises: VolumeBackendAPIException, NotImplementedError
        """
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        model_update = {'status': fields.GroupStatus.AVAILABLE}

        LOG.info("Create generic volume group: %(group)s.",
                 {'group': group.id})

        vol_grp_name = self.utils.update_volume_group_name(group)

        try:
            array, __ = self.utils.get_volume_group_utils(
                group, self.interval, self.retries)
            interval_retries_dict = self.utils.get_intervals_retries_dict(
                self.interval, self.retries)
            self.provision.create_volume_group(
                array, vol_grp_name, interval_retries_dict)
        except Exception:
            exception_message = (_("Failed to create generic volume group:"
                                   " %(volGrpName)s.")
                                 % {'volGrpName': vol_grp_name})
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

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
        if not volume_utils.is_group_a_cg_snapshot_type(group):
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
        array, extraspecs_dict_list = self.utils.get_volume_group_utils(
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
        intervals_retries_dict = self.utils.get_intervals_retries_dict(
            self.interval, self.retries)
        deleted_volume_device_ids = []
        try:
            # If there are no volumes in sg then delete it
            if not volume_device_ids:
                self.rest.delete_storage_group(array, vol_grp_name)
                model_update = {'status': fields.GroupStatus.DELETED}
                volumes_model_update = self.utils.update_volume_model_updates(
                    volumes_model_update, volumes, group.id, status='deleted')
                return model_update, volumes_model_update
            # First remove all the volumes from the SG
            self.masking.remove_volumes_from_storage_group(
                array, volume_device_ids, vol_grp_name, intervals_retries_dict)
            for vol in volumes:
                for extraspecs_dict in extraspecs_dict_list:
                    if vol.volume_type_id in extraspecs_dict['volumeTypeId']:
                        extraspecs = extraspecs_dict.get(utils.EXTRA_SPECS)
                        device_id = self._find_device_on_array(vol,
                                                               extraspecs)
                        if device_id in volume_device_ids:
                            self._remove_vol_and_cleanup_replication(
                                array, device_id,
                                vol.name, extraspecs, vol)
                            self._delete_from_srp(
                                array, device_id, "group vol", extraspecs)
                        else:
                            LOG.debug("Volume not present in storage group.")
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
            # Update the volumes_model_update
            volumes_not_deleted = []
            for vol in volume_device_ids:
                if vol not in deleted_volume_device_ids:
                    volumes_not_deleted.append(vol)
            if not deleted_volume_device_ids:
                volumes_model_update = self.utils.update_volume_model_updates(
                    volumes_model_update,
                    deleted_volume_device_ids,
                    group.id, status='deleted')
            if not volumes_not_deleted:
                volumes_model_update = self.utils.update_volume_model_updates(
                    volumes_model_update,
                    volumes_not_deleted,
                    group.id, status='deleted')
            # As a best effort try to add back the undeleted volumes to sg
            # Dont throw any exception in case of failure
            try:
                if not volumes_not_deleted:
                    self.masking.add_volumes_to_storage_group(
                        array, volumes_not_deleted,
                        vol_grp_name, intervals_retries_dict)
            except Exception as ex:
                LOG.error("Error in rollback - %(ex)s. "
                          "Failed to add back volumes to sg %(sg_name)s",
                          {'ex': ex, 'sg_name': vol_grp_name})

        return model_update, volumes_model_update

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
            self._create_group_replica(source_group,
                                       snap_name)

        except Exception as e:
            exception_message = (_("Failed to create snapshot for group: "
                                   "%(volGrpName)s. Exception received: %(e)s")
                                 % {'volGrpName': grp_id,
                                    'e': six.text_type(e)})
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        for snapshot in snapshots:
            snapshots_model_update.append(
                {'id': snapshot.id,
                 'status': fields.SnapshotStatus.AVAILABLE})
        model_update = {'status': fields.GroupStatus.AVAILABLE}

        return model_update, snapshots_model_update

    def _create_group_replica(
            self, source_group, snap_name):
        """Create a group replica.

        This can be a group snapshot or a cloned volume group.
        :param source_group: the group object
        :param snap_name: the name of the snapshot
        """
        array, __ = (
            self.utils.get_volume_group_utils(
                source_group, self.interval, self.retries))
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
                data=exception_message)
        interval_retries_dict = self.utils.get_intervals_retries_dict(
            self.interval, self.retries)
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
        model_update = {}
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
            array, __ = (
                self.utils.get_volume_group_utils(
                    source_group, self.interval, self.retries))
            # Get the volume group dict for getting the group name
            volume_group = (
                self._find_volume_group(array, source_group))
            if volume_group:
                if 'name' in volume_group:
                    vol_grp_name = volume_group['name']
            if vol_grp_name is None:
                exception_message = (
                    _("Cannot find generic volume group %(grp_id)s.") %
                    {'group_id': source_group.id})
                raise exception.VolumeBackendAPIException(
                    data=exception_message)
            # Check if the snapshot exists
            if 'snapVXSnapshots' in volume_group:
                if snap_name in volume_group['snapVXSnapshots']:
                    self.provision.delete_group_replica(array,
                                                        snap_name,
                                                        vol_grp_name)
            else:
                # Snapshot has been already deleted, return successfully
                LOG.error("Cannot find group snapshot %(snapId)s.",
                          {'snapId': group_snapshot.id})
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
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()

        array, __ = self.utils.get_volume_group_utils(
            group, self.interval, self.retries)
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        add_vols = [vol for vol in add_volumes] if add_volumes else []
        add_device_ids = self._get_volume_device_ids(add_vols, array)
        remove_vols = [vol for vol in remove_volumes] if remove_volumes else []
        remove_device_ids = self._get_volume_device_ids(remove_vols, array)
        vol_grp_name = None
        try:
            volume_group = self._find_volume_group(
                array, group)
            if volume_group:
                if 'name' in volume_group:
                    vol_grp_name = volume_group['name']
            if vol_grp_name is None:
                raise exception.GroupNotFound(
                    group_id=group.id)
            interval_retries_dict = self.utils.get_intervals_retries_dict(
                self.interval, self.retries)
            # Add volume(s) to the group
            if add_device_ids:
                self.masking.add_volumes_to_storage_group(
                    array, add_device_ids, vol_grp_name, interval_retries_dict)
            # Remove volume(s) from the group
            if remove_device_ids:
                self.masking.remove_volumes_from_storage_group(
                    array, remove_device_ids,
                    vol_grp_name, interval_retries_dict)
        except exception.GroupNotFound:
            raise
        except Exception as ex:
            exception_message = (_("Failed to update volume group:"
                                   " %(volGrpName)s. Exception: %(ex)s.")
                                 % {'volGrpName': group.id,
                                    'ex': ex})
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        return model_update, None, None

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
        # Check if we need to create a snapshot
        create_snapshot = False
        volumes_model_update = []
        if group_snapshot:
            source_vols_or_snapshots = snapshots
            source_id = group_snapshot.id
            actual_source_grp = group_snapshot
        elif source_group:
            source_vols_or_snapshots = source_vols
            source_id = source_group.id
            actual_source_grp = source_group
            create_snapshot = True
        else:
            exception_message = (_("Must supply either group snapshot or "
                                   "a source group."))
            raise exception.VolumeBackendAPIException(
                data=exception_message)

        LOG.debug("Enter VMAX create_volume group_from_src. Group to be "
                  "created: %(grpId)s, Source : %(SourceGrpId)s.",
                  {'grpId': group.id,
                   'SourceGrpId': source_id})

        tgt_name = self.utils.update_volume_group_name(group)
        self.create_group(context, group)
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        snap_name = None
        try:
            array, extraspecs_dict_list = (
                self.utils.get_volume_group_utils(
                    group, self.interval, self.retries))
            vol_grp_name = ""
            # Create the target devices
            dict_volume_dicts = {}
            target_volume_names = {}
            for volume, source_vol_or_snapshot in zip(
                    volumes, source_vols_or_snapshots):
                if 'size' in source_vol_or_snapshot:
                    volume_size = source_vol_or_snapshot['size']
                else:
                    volume_size = source_vol_or_snapshot['volume_size']
                for extraspecs_dict in extraspecs_dict_list:
                    if volume.volume_type_id in (
                            extraspecs_dict['volumeTypeId']):
                        extraspecs = extraspecs_dict.get(utils.EXTRA_SPECS)
                        # Create a random UUID and use it as volume name
                        target_volume_name = six.text_type(uuid.uuid4())
                        volume_dict = self.provision.create_volume_from_sg(
                            array, target_volume_name,
                            tgt_name, volume_size, extraspecs)
                        dict_volume_dicts[volume.id] = volume_dict
                        target_volume_names[volume.id] = target_volume_name

            if create_snapshot is True:
                # We have to create a snapshot of the source group
                snap_name = self.utils.truncate_string(group.id, 19)
                self._create_group_replica(actual_source_grp, snap_name)
                vol_grp_name = self.utils.update_volume_group_name(
                    source_group)
            else:
                # We need to check if the snapshot exists
                snap_name = self.utils.truncate_string(source_id, 19)
                source_group = actual_source_grp.get('group')
                volume_group = self._find_volume_group(array, source_group)
                if volume_group is not None:
                    if 'snapVXSnapshots' in volume_group:
                        if snap_name in volume_group['snapVXSnapshots']:
                            LOG.info("Snapshot is present on the array")
                    if 'name' in volume_group:
                        vol_grp_name = volume_group['name']
            # Link and break the snapshot to the source group
            interval_retries_dict = self.utils.get_intervals_retries_dict(
                self.interval, self.retries)
            self.provision.link_and_break_replica(
                array, vol_grp_name, tgt_name, snap_name,
                interval_retries_dict, delete_snapshot=create_snapshot)

        except Exception:
            exception_message = (_("Failed to create vol grp %(volGrpName)s"
                                   " from source %(grpSnapshot)s.")
                                 % {'volGrpName': group.id,
                                    'grpSnapshot': source_id})
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)
        volumes_model_update = self.utils.update_volume_model_updates(
            volumes_model_update, volumes, group.id, model_update['status'])

        # Update the provider_location
        for volume_model_update in volumes_model_update:
            if volume_model_update['id'] in dict_volume_dicts:
                volume_model_update.update(
                    {'provider_location': six.text_type(
                        dict_volume_dicts[volume_model_update['id']])})

        # Update the volumes_model_update with admin_metadata
        self.utils.update_admin_metadata(volumes_model_update,
                                         key='targetVolumeName',
                                         values=target_volume_names)

        return model_update, volumes_model_update
