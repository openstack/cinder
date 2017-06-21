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
import os.path
import sys

from oslo_config import cfg
from oslo_log import log as logging
import six

from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.dell_emc.vmax import masking
from cinder.volume.drivers.dell_emc.vmax import provision
from cinder.volume.drivers.dell_emc.vmax import rest
from cinder.volume.drivers.dell_emc.vmax import utils


LOG = logging.getLogger(__name__)

CONF = cfg.CONF

CINDER_EMC_CONFIG_FILE = '/etc/cinder/cinder_dell_emc_config.xml'
CINDER_EMC_CONFIG_FILE_PREFIX = '/etc/cinder/cinder_dell_emc_config_'
CINDER_EMC_CONFIG_FILE_POSTFIX = '.xml'
BACKENDNAME = 'volume_backend_name'


vmax_opts = [
    cfg.StrOpt('cinder_dell_emc_config_file',
               default=CINDER_EMC_CONFIG_FILE,
               help='Use this file for cinder emc plugin '
                    'config data.'),
    cfg.StrOpt('intervals',
               default=3,
               help='Use this value to specify '
                    'length of intervals in seconds.'),
    cfg.StrOpt('retries',
               default=200,
               help='Use this value to specify '
                    'number of retries.'),
    cfg.BoolOpt('initiator_check',
                default=False,
                help='Use this value to enable '
                     'the initiator_check.')]

CONF.register_opts(vmax_opts)


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
             'volume_backend_name': None}

    pool_info = {'backend_name': None,
                 'config_file': None,
                 'arrays_info': {},
                 'max_over_subscription_ratio': None,
                 'reserved_percentage': 0}

    def __init__(self, prtcl, version, configuration=None):

        self.protocol = prtcl
        self.configuration = configuration
        self.configuration.append_config_values(vmax_opts)
        self.rest = rest.VMAXRest()
        self.utils = utils.VMAXUtils()
        self.masking = masking.VMAXMasking(prtcl, self.rest)
        self.provision = provision.VMAXProvision(self.rest)
        self.version = version
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
        self.intervals = self.configuration.safe_get('intervals')
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

    def _get_slo_workload_combinations(self, array_info):
        """Method to query the array for SLO and Workloads.

        Takes the arrayinfolist object and generates a set which has
        all available SLO & Workload combinations
        :param array_info: the array information
        :returns: finalarrayinfolist
        :raises VolumeBackendAPIException:
        """
        try:
            array = array_info['SerialNumber']
            # Get the srp slo & workload settings
            slo_settings = self.rest.get_slo_list(array)
            # Remove 'None' from the list (so a 'None' slo is not combined
            # with a workload, which is not permitted)
            slo_settings = [x for x in slo_settings
                            if x.lower() not in ['none']]
            workload_settings = self.rest.get_workload_settings(array)
            workload_settings.append("None")
            slo_workload_set = set(
                ['%(slo)s:%(workload)s' % {'slo': slo, 'workload': workload}
                 for slo in slo_settings for workload in workload_settings])
            # Add back in in the only allowed 'None' slo/ workload combination
            slo_workload_set.add('None:None')

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
        :raises VolumeBackendAPIException:
        """
        LOG.debug("Entering create_volume_from_snapshot.")
        model_update = {}
        extra_specs = self._initial_setup(snapshot)

        clone_dict = self._create_cloned_volume(
            volume, snapshot, extra_specs, is_snapshot=False,
            from_snapvx=True)

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
        extra_specs = self._initial_setup(source_volume)
        clone_dict = self._create_cloned_volume(clone_volume, source_volume,
                                                extra_specs)

        model_update.update(
            {'provider_location': six.text_type(clone_dict)})
        return model_update

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
        if not sourcedevice_id or not snap_name:
            LOG.info("No snapshot found on the array")
        else:
            self.provision.delete_volume_snap_check_for_links(
                extra_specs[utils.ARRAY], snap_name,
                sourcedevice_id, extra_specs)
            LOG.info("Leaving delete_snapshot: %(ssname)s.",
                     {'ssname': snap_name})

    def _remove_members(self, array, volume, device_id, extra_specs):
        """This method unmaps a volume from a host.

        Removes volume from the storage group that belongs to a masking view.
        :param array: the array serial number
        :param volume: volume object
        :param device_id: the VMAX volume device id
        :param extra_specs: extra specifications
        """
        volume_name = volume.name
        LOG.debug("Detaching volume %s.", volume_name)
        return self.masking.remove_and_reset_members(
            array, device_id, volume_name, extra_specs, True)

    def _unmap_lun(self, volume, connector):
        """Unmaps a volume from the host.

        :param volume: the volume Object
        :param connector: the connector Object
        :raises VolumeBackendAPIException:
        """
        device_info = {}
        extra_specs = self._initial_setup(volume)
        volume_name = volume.name
        LOG.info("Unmap volume: %(volume)s.",
                 {'volume': volume_name})
        if connector is not None:
            device_info = self.find_host_lun_id(
                volume, connector['host'], extra_specs)
        if 'hostlunid' not in device_info:
            LOG.info("Volume %s is not mapped. No volume to unmap.",
                     volume_name)
            return

        device_id = self._find_device_on_array(volume, extra_specs)
        array = extra_specs[utils.ARRAY]
        self._remove_members(array, volume, device_id, extra_specs)

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
        :raises VolumeBackendAPIException:
        """
        extra_specs = self._initial_setup(volume)
        is_multipath = connector.get('multipath', False)

        volume_name = volume.name
        LOG.info("Initialize connection: %(volume)s.",
                 {'volume': volume_name})
        device_info_dict = self.find_host_lun_id(
            volume, connector['host'], extra_specs)
        masking_view_dict = self._populate_masking_dict(
            volume, connector, extra_specs)

        if ('hostlunid' in device_info_dict and
                device_info_dict['hostlunid'] is not None):
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
            device_info_dict, port_group_name = (
                self._attach_volume(
                    volume, connector, extra_specs, masking_view_dict))
        if self.protocol.lower() == 'iscsi':
            device_info_dict['ip_and_iqn'] = (
                self._find_ip_and_iqns(
                    extra_specs[utils.ARRAY], port_group_name))
            device_info_dict['is_multipath'] = is_multipath
        return device_info_dict

    def _attach_volume(self, volume, connector, extra_specs,
                       masking_view_dict):
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

        rollback_dict = self.masking.setup_masking_view(
            masking_view_dict[utils.ARRAY],
            masking_view_dict, extra_specs)

        # Find host lun id again after the volume is exported to the host.
        device_info_dict = self.find_host_lun_id(volume, connector['host'],
                                                 extra_specs)
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

        return device_info_dict, rollback_dict['port_group_name']

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
        :raises VolumeBackendAPIException:
        """
        original_vol_size = volume.size
        volume_name = volume.name
        extra_specs = self._initial_setup(volume)
        device_id = self._find_device_on_array(volume, extra_specs)
        array = extra_specs[utils.ARRAY]
        # check if volume is part of an on-going clone operation
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
        self.provision.extend_volume(array, device_id, new_size, extra_specs)

        LOG.debug("Leaving extend_volume: %(volume_name)s. ",
                  {'volume_name': volume_name})

    def update_volume_stats(self):
        """Retrieve stats info."""
        pools = []
        # Dictionary to hold the arrays for which the SRP details
        # have already been queried.
        # This only applies to the arrays for which WLP is not enabled
        arrays = {}
        wlp_enabled = False
        total_capacity_gb = 0
        free_capacity_gb = 0
        provisioned_capacity_gb = 0
        location_info = None
        backend_name = self.pool_info['backend_name']
        max_oversubscription_ratio = (
            self.pool_info['max_over_subscription_ratio'])
        reserved_percentage = self.pool_info['reserved_percentage']
        array_max_over_subscription = None
        array_reserve_percent = None
        array_info_list = self.pool_info['arrays_info']
        already_queried = False
        for array_info in array_info_list:
            # Add both SLO & Workload name in the pool name
            # Query the SRP only once if WLP is not enabled
            # Only insert the array details in the dict once
            self.rest.set_rest_credentials(array_info)
            if array_info['SerialNumber'] not in arrays:
                (location_info, total_capacity_gb, free_capacity_gb,
                 provisioned_capacity_gb,
                 array_reserve_percent,
                 wlp_enabled) = self._update_srp_stats(array_info)
            else:
                already_queried = True
            pool_name = ("%(slo)s+%(workload)s+%(srpName)s+%(array)s"
                         % {'slo': array_info['SLO'],
                            'workload': array_info['Workload'],
                            'srpName': array_info['srpName'],
                            'array': array_info['SerialNumber']})
            if wlp_enabled is False:
                arrays[array_info['SerialNumber']] = (
                    [total_capacity_gb, free_capacity_gb,
                     provisioned_capacity_gb, array_reserve_percent])

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
                        'max_over_subscription_ratio':
                            max_oversubscription_ratio,
                        'reserved_percentage': reserved_percentage}
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
                        'consistent_group_snapshot_enabled': False,
                        'max_over_subscription_ratio':
                            max_oversubscription_ratio,
                        'reserved_percentage': reserved_percentage}
                if array_reserve_percent:
                    if isinstance(reserved_percentage, int):
                        if array_reserve_percent > reserved_percentage:
                            pool['reserved_percentage'] = array_reserve_percent
                    else:
                        pool['reserved_percentage'] = array_reserve_percent

            if array_max_over_subscription:
                pool['max_over_subscription_ratio'] = (
                    self.utils.override_ratio(
                        max_oversubscription_ratio,
                        array_max_over_subscription))
            pools.append(pool)

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
         provisionedManagedSpaceGbs, array_reserve_percent,
         wlpEnabled) = (
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
                array_reserve_percent, wlpEnabled)

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
        extra_specs = self.utils.get_volumetype_extra_specs(
            volume, volume_type_id)
        config_group = None
        # If there are no extra specs then the default case is assumed.
        if extra_specs:
            config_group = self.configuration.config_group
        config_file = self._register_config_file_from_config_group(
            config_group)
        return extra_specs, config_file

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
            device_id = name['device_id']
            element_name = self.utils.get_volume_element_name(
                volume_name)
            founddevice_id = self.rest.find_volume_device_id(
                array, element_name)

            # Allow for an external app to delete the volume.
            if device_id and device_id != founddevice_id:
                founddevice_id = None

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
        :param host: host from connector
        :param extra_specs: the extra specs
        :returns: dict -- the data dict
        """
        maskedvols = {}
        volume_name = volume.name
        device_id = self._find_device_on_array(volume, extra_specs)
        if device_id:
            array = extra_specs[utils.ARRAY]
            host = self.utils.get_host_short_name(host)
            # return only masking views for this host
            maskingviews = self.get_masking_views_from_volume(
                array, device_id, host)

            for maskingview in maskingviews:
                host_lun_id = self.rest.find_mv_connections_for_vol(
                    array, maskingview, device_id)
                if host_lun_id is not None:
                    devicedict = {'hostlunid': host_lun_id,
                                  'maskingview': maskingview,
                                  'array': array}
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
        else:
            exception_message = (_("Cannot retrieve volume %(vol)s "
                                   "from the array.") % {'vol': volume_name})
            LOG.exception(exception_message)
            raise exception.VolumeBackendAPIException(exception_message)

        return maskedvols

    def get_masking_views_from_volume(self, array, device_id, host):
        """Retrieve masking view list for a volume.

        :param array: array serial number
        :param device_id: the volume device id
        :param host: the host
        :return: masking view list
        """
        LOG.debug("Getting masking views from volume")
        maskingview_list = []
        short_host = self.utils.get_host_short_name(host)
        storagegrouplist = self.rest.get_storage_groups_from_volume(
            array, device_id)
        for sg in storagegrouplist:
            mvs = self.rest.get_masking_views_from_storage_group(
                array, sg)
            for mv in mvs:
                if short_host.lower() in mv.lower():
                    maskingview_list.append(mv)
        return maskingview_list

    def _register_config_file_from_config_group(self, config_group_name):
        """Given the config group name register the file.

        :param config_group_name: the config group name
        :returns: string -- configurationFile - name of the configuration file
        :raises VolumeBackendAPIException:
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
        :raises VolumeBackendAPIException:
        """
        try:
            extra_specs, config_file = (
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
        slo = extra_specs[utils.SLO]
        workload = extra_specs[utils.WORKLOAD]
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
        else:
            child_sg_name = (
                "OS-%(shortHostName)s-No_SLO-%(pg)s"
                % {'shortHostName': short_host_name,
                   'pg': short_pg_name})

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
        :raises VolumeBackendAPIException:
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
        :return: sourcedevice_id, foundsnap_name
        """
        foundsnap_name = None
        sourcedevice_id = None
        volume_name = snapshot.id

        loc = snapshot.provider_location

        if isinstance(loc, six.string_types):
            name = ast.literal_eval(loc)
            sourcedevice_id = name['source_id']
            snap_name = name['snap_name']
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
        :return: snap_dict
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
        # check if volume is snap source
        self._sync_check(array, device_id, volume_name, extra_specs)
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
        :raises VolumeBackendAPIException:
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

        storagegroup_name = self.masking.get_or_create_default_storage_group(
            array, extra_specs[utils.SRP], extra_specs[utils.SLO],
            extra_specs[utils.WORKLOAD], extra_specs)
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
        on the volume type (e.g. 'port_group_name = os-pg1-pg'), or can
        be chosen from a list which must be provided in the xml file, e.g.:
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
                               "please configure the 'port_group_name' extra "
                               "spec on the volume type, or enter a list of "
                               "portgroups to the xml file associated with "
                               "this backend e.g."
                               "<PortGroups>"
                               "    <PortGroup>OS-PORTGROUP1-PG</PortGroup>"
                               "    <PortGroup>OS-PORTGROUP2-PG</PortGroup>"
                               "</PortGroups>."))
            LOG.exception(error_message)
            raise exception.VolumeBackendAPIException(data=error_message)

        extra_specs[utils.INTERVAL] = self.intervals
        LOG.debug("The interval is set at: %(intervalInSecs)s.",
                  {'intervalInSecs': self.intervals})
        extra_specs[utils.RETRIES] = self.retries
        LOG.debug("Retries are set at: %(retries)s.",
                  {'retries': self.retries})

        # set pool_name slo and workload
        if 'pool_name' in extra_specs:
            pool_name = extra_specs['pool_name']
        else:
            slo_list = self.rest.get_slo_list(pool_record['SerialNumber'])
            if 'Optimized' in slo_list:
                slo = 'Optimized'
            elif 'Diamond' in slo_list:
                slo = 'Diamond'
            else:
                slo = 'None'
            pool_name = ("%(slo)s+%(workload)s+%(srpName)s+%(array)s"
                         % {'slo': slo,
                            'workload': 'None',
                            'srpName': pool_record['srpName'],
                            'array': pool_record['SerialNumber']})
            LOG.warning("Pool_name is not present in the extra_specs "
                        "- using default pool %(pool_name)s.",
                        {'pool_name': pool_name})
        pool_details = pool_name.split('+')
        slo_from_extra_spec = pool_details[0]
        workload_from_extra_spec = pool_details[1]
        # standardize slo and workload 'NONE' naming conventions
        if workload_from_extra_spec.lower() == 'none':
            workload_from_extra_spec = 'NONE'
        if slo_from_extra_spec.lower() == 'none':
            slo_from_extra_spec = None
        extra_specs[utils.SLO] = slo_from_extra_spec
        extra_specs[utils.WORKLOAD] = workload_from_extra_spec

        LOG.debug("SRP is: %(srp)s "
                  "Array is: %(array)s "
                  "SLO is: %(slo)s "
                  "Workload is: %(workload)s.",
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
        :raises VolumeBackendAPIException:
        """
        # Check if it is part of a storage group and delete it
        # extra logic for case when volume is the last member.
        self.masking.remove_and_reset_members(
            array, device_id, volume_name, extra_specs, False)

        try:
            LOG.debug("Delete Volume: %(name)s. device_id: %(device_id)s.",
                      {'name': volume_name, 'device_id': device_id})
            self.provision.delete_volume_from_srp(
                array, device_id, volume_name)

        except Exception as e:
            # If we cannot successfully delete the volume, then we want to
            # return the volume to the default storage group,
            # which should be the SG it previously belonged to.
            self.masking.return_volume_to_default_storage_group(
                array, device_id, volume_name, extra_specs)

            error_message = (_("Failed to delete volume %(volume_name)s. "
                               "Exception received: %(e)s") %
                             {'volume_name': volume_name,
                              'e': six.text_type(e)})
            LOG.exception(error_message)
            raise exception.VolumeBackendAPIException(data=error_message)

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
        :return: list of masking views
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
        LOG.debug("The portgroup name for iscsiadm is %(pg)s.",
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

    def _cleanup_target(self, array, target_device_id, source_device_id,
                        clone_name, snap_name, extra_specs):
        """Cleanup target volume on failed clone/ snapshot creation.

        :param array: the array serial number
        :param target_device_id: the target device ID
        :param source_device_id: the source device ID
        :param clone_name: the name of the clone volume
        :param extra_specs: the extra specifications
        """
        snap_session = self.rest._get_sync_session(
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
                        array, target, source, snap_name,
                        extra_specs, wait_for_sync=True)
                if 'temp' in snap_name:
                    self.provision.delete_temp_volume_snap(
                        array, snap_name, source)

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
        # Rename the volume
        volume_name = self.utils.get_volume_element_name(volume_id)
        LOG.debug("Rename volume %(vol)s to %(elementName)s.",
                  {'vol': volume_id,
                   'elementName': volume_name})
        self.rest.rename_volume(array, device_id, volume_name)

        provider_location = {'device_id': device_id, 'array': array}

        model_update = {'provider_location': six.text_type(provider_location),
                        'display_name': volume_name}
        return model_update

    def _check_lun_valid_for_cinder_management(
            self, array, device_id, volume_id, external_ref):
        """Check if a volume is valid for cinder management.

        :param array: the array serial number
        :param device_id: the device id
        :param volume_id: the cinder volume id
        :param external_ref: the external reference
        :raises ManageExistingInvalidReference, ManageExistingAlreadyManaged:
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
        size = float(self.rest.get_size_of_device_on_array(array, device_id))
        LOG.debug("Size of volume %(device_id)s is %(volumeSize)s GB.",
                  {'device_id': device_id, 'volumeSize': int(size)})
        return int(size)

    def unmanage(self, volume):
        """Export VMAX volume from Cinder.

        Leave the volume intact on the backend array.
        :param volume: the volume object
        :raises VolumeBackendAPIException:
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
            # Rename the volume to volumeId, thus remove the 'OS-' prefix.
            self.rest.rename_volume(
                extra_specs[utils.ARRAY], device_id, volume_id)

    def retype(self, volume, host):
        """Migrate volume to another host using retype.

        :param volume: the volume object including the volume_type_id
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
                                            volume_name, extra_specs)

    def _slo_workload_migration(self, device_id, volume, host,
                                volume_name, extra_specs):
        """Migrate from SLO/Workload combination to another.

        :param device_id: the volume device id
        :param volume: the volume object
        :param host: the host dict
        :param volume_name: the name of the volume
        :param extra_specs: extra specifications
        :returns: boolean -- True if migration succeeded, False if error.
        """
        is_valid, target_slo, target_workload = (
            self._is_valid_for_storage_assisted_migration(
                device_id, host, extra_specs[utils.ARRAY],
                extra_specs[utils.SRP], volume_name))

        if not is_valid:
            LOG.error(
                "Volume %(name)s is not suitable for storage "
                "assisted migration using retype.",
                {'name': volume_name})
            return False
        if volume.host != host['host']:
            LOG.debug(
                "Retype Volume %(name)s from source host %(sourceHost)s "
                "to target host %(targetHost)s. ",
                {'name': volume_name,
                 'sourceHost': volume.host,
                 'targetHost': host['host']})
            return self._migrate_volume(
                extra_specs[utils.ARRAY], device_id,
                extra_specs[utils.SRP], target_slo,
                target_workload, volume_name, extra_specs)

        return False

    def _migrate_volume(
            self, array, device_id, srp, target_slo,
            target_workload, volume_name, extra_specs):
        """Migrate from one slo/workload combination to another.

        This requires moving the volume from its current SG to a
        new or existing SG that has the target attributes.
        :param array: the array serial number
        :param device_id: the device number
        :param srp: the storage resource pool
        :param target_slo: the target service level
        :param target_workload: the target workload
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        :return: bool
        """
        storagegroups = self.rest.get_storage_groups_from_volume(
            array, device_id)
        if not storagegroups:
            LOG.warning(
                "Volume : %(volume_name)s does not currently "
                "belong to any storage groups.",
                {'volume_name': volume_name})
        else:
            self.masking.remove_and_reset_members(
                array, device_id, None, extra_specs, False)

        try:
            target_sg_name = self.masking.get_or_create_default_storage_group(
                array, srp, target_slo, target_workload, extra_specs)
        except Exception as e:
            LOG.error("Failed to get or create storage group. "
                      "Exception received was %(e)s.", {'e': e})
            return False

        self.masking.add_volume_to_storage_group(
            array, device_id, target_sg_name, volume_name, extra_specs)
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
            source_srp, volume_name):
        """Check if volume is suitable for storage assisted (pool) migration.

        :param device_id: the volume device id
        :param host: the host dict
        :param source_array: the volume's current array serial number
        :param source_srp: the volume's current pool name
        :param volume_name: the name of the volume to be migrated
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
                if target_combination in emc_fast_setting:
                    LOG.warning(
                        "No action required. Volume: %(volume_name)s is "
                        "already part of slo/workload combination: "
                        "%(targetCombination)s.",
                        {'volume_name': volume_name,
                         'targetCombination': target_combination})
                    return false_ret

        return True, target_slo, target_workload
