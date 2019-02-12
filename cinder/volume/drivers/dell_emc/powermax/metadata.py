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
import datetime
import platform
import prettytable
import six
import time
import types

from oslo_log import log as logging

from cinder.objects import volume
from cinder import version

from cinder.volume.drivers.dell_emc.powermax import utils
LOG = logging.getLogger(__name__)
CLEANUP_LIST = ['masking_view', 'child_storage_group', 'parent_storage_group',
                'initiator_group', 'port_group', 'storage_group']


def debug_required(func):
    """Only execute the function if debug is enabled."""

    def func_wrapper(*args, **kwargs):
        try:
            if args[0].is_debug:
                return func(*args, **kwargs)
            else:
                pass
        except Exception as ex:
            LOG.warning("Volume metadata logging failure. "
                        "Exception is %s.", ex)

    return func_wrapper


class PowerMaxVolumeMetadata(object):
    """Gathers PowerMax/VMAX specific volume information.

    Also gathers Unisphere, Microcode OS/distribution and python versions.
    """

    def __init__(self, rest, version, is_debug):
        self.version_dict = {}
        self.rest = rest
        self.utils = utils.PowerMaxUtils()
        self.volume_trace_list = []
        self.is_debug = is_debug
        self.powermax_driver_version = version

    def _update_platform(self):
        """Update the platform."""
        try:
            self.version_dict['openstack_platform'] = platform.platform()
        except Exception as ex:
            LOG.warning("Unable to determine the platform. "
                        "Exception is %s.", ex)

    def _get_python_version(self):
        """Get the python version."""
        try:
            self.version_dict['python_version'] = platform.python_version()
        except Exception as ex:
            LOG.warning("Unable to determine the python version. "
                        "Exception is %s.", ex)

    def _update_version_from_version_string(self):
        """Update the version from the version string."""
        try:
            self.version_dict['openstack_version'] = (
                version.version_info.version_string())
        except Exception as ex:
            LOG.warning("Unable to determine the OS version. "
                        "Exception is %s.", ex)

    def _update_release_from_release_string(self):
        """Update the release from the release string."""
        try:
            self.version_dict['openstack_release'] = (
                version.version_info.release_string())
        except Exception as ex:
            LOG.warning("Unable to get release info. "
                        "Exception is %s.", ex)

    @staticmethod
    def _get_version_info_version():
        """Gets the version.

        :returns: string -- version
        """
        return version.version_info.version

    def _update_info_from_version_info(self):
        """Update class variables from version info."""
        try:
            ver = self._get_version_info_version()
            if ver:
                self.version_dict['openstack_version'] = ver
        except Exception as ex:
            LOG.warning("Unable to get version info. "
                        "Exception is %s.", ex)

    def _update_openstack_info(self):
        """Update openstack info."""
        self._update_version_from_version_string()
        self._update_release_from_release_string()
        self._update_platform()
        self._get_python_version()
        # Some distributions override with more meaningful information
        self._update_info_from_version_info()

    def _update_array_info(self, serial_number):
        """Update PowerMax/VMAX info.

        :param serial_number: the serial number of the array
        """
        u4p_version_dict = (
            self.rest.get_unisphere_version())
        self.version_dict['unisphere_for_powermax_version'] = (
            u4p_version_dict['version'])
        self.version_dict['serial_number'] = serial_number
        array_info_dict = self.rest.get_array_detail(serial_number)
        self.version_dict['storage_firmware_version'] = (
            array_info_dict['ucode'])
        self.version_dict['storage_model'] = array_info_dict['model']
        self.version_dict['powermax_cinder_driver_version'] = (
            self.powermax_driver_version)

    @debug_required
    def gather_version_info(self, serial_number):
        """Gather info on the array

        :param serial_number: the serial number of the array
        :returns: version_dict
        """
        try:
            self._update_openstack_info()
            self._update_array_info(serial_number)
            self.print_pretty_table(self.version_dict)
        except Exception as ex:
            LOG.warning("Unable to gather version info. "
                        "Exception is %s.", ex)
        return self.version_dict

    @debug_required
    def gather_volume_info(
            self, volume_id, successful_operation, append, **kwargs):
        """Gather volume information.

        :param volume_id: the unique volume id key
        :param successful_operation: the operation e.g "create"
        :param append: append flag
        :param kwargs: variable length argument list
        :returns: datadict
        """
        volume_trace_dict = {}
        volume_key_value = {}
        datadict = {}
        try:
            volume_trace_dict = self._fill_volume_trace_dict(
                volume_id, successful_operation, append, **kwargs)
            volume_trace_dict['volume_updated_time'] = (
                datetime.datetime.fromtimestamp(
                    int(time.time())).strftime('%Y-%m-%d %H:%M:%S'))
            volume_key_value[volume_id] = volume_trace_dict
            if not self.volume_trace_list:
                self.volume_trace_list.append(volume_key_value.copy())
            else:
                self._consolidate_volume_trace_list(
                    volume_id, volume_trace_dict, volume_key_value)
            for datadict in list(self.volume_trace_list):
                if volume_id in datadict:
                    if not append:
                        self.volume_trace_list.remove(datadict)
                    return datadict
        except Exception as ex:
            LOG.warning("Exception in gather volume metadata. "
                        "Exception is %s.", ex)
        return datadict

    def _fill_volume_trace_dict(
            self, volume_id, successful_operation, append, **kwargs):
        """Populates a dictionary with key value pairs

        :param volume_id: the unique volume id key
        :param successful_operation: the operation e.g "create"
        :param append: append flag
        :param kwargs: variable length argument list
        :returns: my_volume_trace_dict
        """
        param_dict = locals()
        my_volume_trace_dict = {}
        for k, v in param_dict.items():
            if self._param_condition(k, v):
                my_volume_trace_dict[k] = v
            if k == 'kwargs':
                for k2, v2 in v.items():
                    if self._param_condition(k2, v2):
                        my_volume_trace_dict[k2] = v2
                    elif k2 == 'mv_list' and v2:
                        for i, item in enumerate(v2, 1):
                            my_volume_trace_dict["masking_view_%d" % i] = item
                    elif k2 == 'sg_list' and v2:
                        for i, item in enumerate(v2, 1):
                            my_volume_trace_dict["storage_group_%d" % i] = item

        return my_volume_trace_dict

    def _param_condition(self, key, value):
        """Determines condition for inclusion.

        :param key: the key
        :param value: the value

        :returns: True or False
        """
        exclude_list = ('self', 'append', 'mv_list', 'sg_list')
        return (value is not None and key not in exclude_list and
                not isinstance(value, (dict,
                                       types.FunctionType,
                                       type)))

    @debug_required
    def print_pretty_table(self, datadict):
        """Prints the data in the dict.

        :param datadict: the data dictionary
        """
        t = prettytable.PrettyTable(['Key', 'Value'])
        for k, v in datadict.items():
            if v is not None:
                t.add_row([k, v])

        LOG.debug('\n%(output)s\n', {'output': t})

    def _consolidate_volume_trace_list(
            self, volume_id, volume_trace_dict, volume_key_value):
        """Consolidate data into self.volume_trace_list

        :param volume_id: the unique volume identifier
        :param volume_trace_dict: the existing dict
        :param volume_key_value: the volume id key and dict value
        """
        is_merged = False
        for datadict in list(self.volume_trace_list):
            if volume_id in datadict:
                for key, dict_value in datadict.items():
                    merged_dict = (
                        self.utils.merge_dicts(
                            volume_trace_dict, dict_value))
                    self.volume_trace_list.remove(datadict)
                    volume_key_value[volume_id] = merged_dict
                    self.volume_trace_list.append(volume_key_value.copy())
                    is_merged = True
        if not is_merged:
            self.volume_trace_list.append(volume_key_value.copy())

    @debug_required
    def update_volume_info_metadata(self, datadict, version_dict):
        """Get update volume metadata with volume info

        :param datadict: volume info key value pairs
        :param version_dict: version dictionary
        :returns: volume_metadata
        """
        return self.utils.merge_dicts(
            version_dict, *datadict.values())

    @debug_required
    def capture_attach_info(
            self, volume, extra_specs, masking_view_dict, host,
            is_multipath, is_multiattach):
        """Captures attach info in volume metadata

        :param volume: the volume object
        :param extra_specs: extra specifications
        :param masking_view_dict: masking view dict
        :param host: host
        :param is_multipath: is mulitipath flag
        :param is_multiattach: is multi attach
        """
        mv_list, sg_list = [], []
        child_storage_group, parent_storage_group = None, None
        initiator_group, port_group = None, None

        if is_multiattach:
            successful_operation = 'multi_attach'
            mv_list = masking_view_dict['mv_list']
            sg_list = masking_view_dict['sg_list']
        else:
            successful_operation = 'attach'
            child_storage_group = masking_view_dict[utils.SG_NAME]
            parent_storage_group = masking_view_dict[utils.PARENT_SG_NAME]
            initiator_group = masking_view_dict[utils.IG_NAME]
            port_group = masking_view_dict[utils.PORTGROUPNAME]

        datadict = self.gather_volume_info(
            volume.id, successful_operation, False,
            serial_number=extra_specs[utils.ARRAY],
            service_level=extra_specs[utils.SLO],
            workload=extra_specs[utils.WORKLOAD], srp=extra_specs[utils.SRP],
            masking_view=masking_view_dict[utils.MV_NAME],
            child_storage_group=child_storage_group,
            parent_storage_group=parent_storage_group,
            initiator_group=initiator_group,
            port_group=port_group,
            host=host, is_multipath=is_multipath,
            identifier_name=self.utils.get_volume_element_name(volume.id),
            openstack_name=volume.display_name,
            mv_list=mv_list, sg_list=sg_list)

        volume_metadata = self.update_volume_info_metadata(
            datadict, self.version_dict)

        self.print_pretty_table(volume_metadata)

    @debug_required
    def capture_detach_info(
            self, volume, extra_specs, device_id, mv_list, sg_list):
        """Captures detach info in volume metadata

        :param volume: the volume object
        :param extra_specs: extra specifications
        :param device_id: masking view dict
        :param mv_list: masking view list
        :param sg_list: storage group list
        """
        default_sg = self.utils.derive_default_sg_from_extra_specs(extra_specs)
        datadict = self.gather_volume_info(
            volume.id, 'detach', False, device_id=device_id,
            serial_number=extra_specs[utils.ARRAY],
            service_level=extra_specs[utils.SLO],
            workload=extra_specs[utils.WORKLOAD], srp=extra_specs[utils.SRP],
            default_sg_name=default_sg,
            identifier_name=self.utils.get_volume_element_name(volume.id),
            openstack_name=volume.display_name,
            mv_list=mv_list, sg_list=sg_list
        )
        volume_metadata = self.update_volume_info_metadata(
            datadict, self.version_dict)
        self.print_pretty_table(volume_metadata)

    @debug_required
    def capture_extend_info(
            self, volume, new_size, device_id, extra_specs, array):
        """Capture extend info in volume metadata

        :param volume: the volume object
        :param new_size: new size
        :param device_id: device id
        :param extra_specs: extra specifications
        :param array: array serial number
        """
        default_sg = self.utils.derive_default_sg_from_extra_specs(extra_specs)
        datadict = self.gather_volume_info(
            volume.id, 'extend', False, volume_size=new_size,
            device_id=device_id,
            default_sg_name=default_sg, serial_number=array,
            service_level=extra_specs[utils.SLO],
            workload=extra_specs[utils.WORKLOAD],
            srp=extra_specs[utils.SRP],
            identifier_name=self.utils.get_volume_element_name(volume.id),
            openstack_name=volume.display_name,
            is_compression_disabled=self.utils.is_compression_disabled(
                extra_specs))
        volume_metadata = self.update_volume_info_metadata(
            datadict, self.version_dict)
        self.print_pretty_table(volume_metadata)

    @debug_required
    def capture_snapshot_info(
            self, source, extra_specs, successful_operation, last_ss_name):
        """Captures snapshot info in volume metadata

        :param source: the source volume object
        :param extra_specs: extra specifications
        :param successful_operation: snapshot operation
        :param last_ss_name: the last snapshot name
        """
        if isinstance(source, volume.Volume):
            if 'create' in successful_operation:
                snapshot_count = six.text_type(len(source.snapshots))
            else:
                snapshot_count = six.text_type(len(source.snapshots) - 1)
            default_sg = (
                self.utils.derive_default_sg_from_extra_specs(extra_specs))
            datadict = self.gather_volume_info(
                source.id, successful_operation, False,
                volume_size=source.size,
                default_sg_name=default_sg,
                serial_number=extra_specs[utils.ARRAY],
                service_level=extra_specs[utils.SLO],
                workload=extra_specs[utils.WORKLOAD],
                srp=extra_specs[utils.SRP],
                identifier_name=(
                    self.utils.get_volume_element_name(source.id)),
                openstack_name=source.display_name,
                snapshot_count=snapshot_count,
                last_ss_name=last_ss_name)
            volume_metadata = self.update_volume_info_metadata(
                datadict, self.version_dict)
            self.print_pretty_table(volume_metadata)

    @debug_required
    def capture_modify_group(
            self, group_name, group_id, add_vols, remove_volumes, array):
        """Captures group info after a modify operation

        :param group_name: group name
        :param group_id: group id
        :param add_vols: add volume list
        :param remove_volumes: remove volume list
        :param array: array serial number
        """
        if not self.version_dict:
            self.version_dict = self.gather_version_info(array)
        for add_vol in add_vols:
            datadict = self.gather_volume_info(
                add_vol.id, 'addToGroup', True,
                group_name=group_name, group_id=group_id)
            add_volume_metadata = self.update_volume_info_metadata(
                datadict, self.version_dict)
            self.print_pretty_table(add_volume_metadata)

        for remove_volume in remove_volumes:
            datadict = self.gather_volume_info(
                remove_volume.id, 'removeFromGroup', True,
                group_name='Removed from %s' % group_name,
                group_id='Removed from %s' % group_id)
            remove_volume_metadata = self.update_volume_info_metadata(
                datadict, self.version_dict)
            self.print_pretty_table(remove_volume_metadata)

    @debug_required
    def capture_create_volume(
            self, device_id, volume, group_name, group_id, extra_specs,
            rep_info_dict, successful_operation, source_snapshot_id=None,
            source_device_id=None, temporary_snapvx=None):
        """Captures create volume info in volume metadata

        :param device_id: device id
        :param volume: volume object
        :param group_name: group name
        :param group_id: group id
        :param extra_specs: additional info
        :param rep_info_dict: information gathered from replication
        :param successful_operation: the type of create operation
        :param source_snapshot_id: the source snapshot id

        :returns: volume_metadata dict
        """
        rdf_group_no, target_name, remote_array, target_device_id = (
            None, None, None, None)
        rep_mode, replication_status, rdf_group_label, use_bias = (
            None, None, None, None)
        target_array_model = None
        if rep_info_dict:
            rdf_group_no = rep_info_dict['rdf_group_no']
            target_name = rep_info_dict['target_name']
            remote_array = rep_info_dict['remote_array']
            target_device_id = rep_info_dict['target_device_id']
            rep_mode = rep_info_dict['rep_mode']
            replication_status = rep_info_dict['replication_status']
            rdf_group_label = rep_info_dict['rdf_group_label']
            if utils.METROBIAS in extra_specs:
                use_bias = extra_specs[utils.METROBIAS]
            target_array_model = rep_info_dict['target_array_model']

        default_sg = self.utils.derive_default_sg_from_extra_specs(
            extra_specs, rep_mode)
        datadict = self.gather_volume_info(
            volume.id, successful_operation, True, volume_size=volume.size,
            device_id=device_id,
            default_sg_name=default_sg,
            serial_number=extra_specs[utils.ARRAY],
            service_level=extra_specs[utils.SLO],
            workload=extra_specs[utils.WORKLOAD],
            srp=extra_specs[utils.SRP],
            identifier_name=self.utils.get_volume_element_name(volume.id),
            openstack_name=volume.display_name,
            source_volid=volume.source_volid,
            group_name=group_name, group_id=group_id,
            rdf_group_no=rdf_group_no,
            target_name=target_name, remote_array=remote_array,
            target_device_id=target_device_id,
            source_snapshot_id=source_snapshot_id,
            rep_mode=rep_mode, replication_status=replication_status,
            rdf_group_label=rdf_group_label, use_bias=use_bias,
            is_compression_disabled=(
                'yes' if self.utils.is_compression_disabled(
                    extra_specs) else 'no'),
            source_device_id=source_device_id,
            temporary_snapvx=temporary_snapvx,
            target_array_model=target_array_model

        )
        volume_metadata = self.update_volume_info_metadata(
            datadict, self.version_dict)
        self.print_pretty_table(volume_metadata)

    @debug_required
    def gather_replication_info(
            self, volume_id, successful_operation, append, **kwargs):
        """Gathers replication information

        :param volume_id: volume id
        :param successful_operation: the successful operation type
        :param append: boolean
        :param **kwargs: variable length of arguments
        :returns: rep_dict
        """
        return self._fill_volume_trace_dict(
            volume_id, successful_operation, append, **kwargs)

    @debug_required
    def capture_failover_volume(
            self, volume, target_device, remote_array, rdf_group, device_id,
            array, extra_specs, failover, vol_grp_name,
            replication_status, rep_mode):
        """Captures failover info in volume metadata

        :param volume: volume object
        :param target_device: the device to failover to
        :param remote_array: the array to failover to
        :param rdf_group: the rdf group
        :param device_id: the device to failover from
        :param array: the array to failover from
        :param extra_specs: additional info
        :param failover: failover flag
        :param vol_grp_name: async group name
        :param replication_status: volume replication status
        :param rep_mode: replication mode
        """
        operation = "Failover" if failover else "Failback"
        datadict = self.gather_volume_info(
            volume.id, operation, True, volume_size=volume.size,
            device_id=target_device,
            serial_number=remote_array,
            service_level=extra_specs[utils.SLO],
            workload=extra_specs[utils.WORKLOAD],
            srp=extra_specs[utils.SRP],
            identifier_name=self.utils.get_volume_element_name(volume.id),
            openstack_name=volume.display_name,
            source_volid=volume.source_volid,
            rdf_group_no=rdf_group, remote_array=array,
            target_device_id=device_id, vol_grp_name=vol_grp_name,
            replication_status=replication_status, rep_mode=rep_mode
        )

        self.version_dict = (
            self.gather_version_info(remote_array))
        volume_metadata = self.update_volume_info_metadata(
            datadict, self.version_dict)
        self.print_pretty_table(volume_metadata)

    @debug_required
    def capture_manage_existing(
            self, volume, rep_info_dict, device_id, extra_specs):
        """Captures manage existing info in volume metadata

        :param volume: volume object
        :param rep_info_dict: information gathered from replication
        :param device_id: the PowerMax/VMAX device id
        :param extra_specs: the extra specs
        """
        successful_operation = "manage_existing_volume"
        rdf_group_no, target_name, remote_array, target_device_id = (
            None, None, None, None)
        rep_mode, replication_status, rdf_group_label = (
            None, None, None)
        if rep_info_dict:
            rdf_group_no = rep_info_dict['rdf_group_no']
            target_name = rep_info_dict['target_name']
            remote_array = rep_info_dict['remote_array']
            target_device_id = rep_info_dict['target_device_id']
            rep_mode = rep_info_dict['rep_mode']
            replication_status = rep_info_dict['replication_status']
            rdf_group_label = rep_info_dict['rdf_group_label']

        default_sg = self.utils.derive_default_sg_from_extra_specs(
            extra_specs, rep_mode)
        datadict = self.gather_volume_info(
            volume.id, successful_operation, True, volume_size=volume.size,
            device_id=device_id,
            default_sg_name=default_sg,
            serial_number=extra_specs[utils.ARRAY],
            service_level=extra_specs[utils.SLO],
            workload=extra_specs[utils.WORKLOAD],
            srp=extra_specs[utils.SRP],
            identifier_name=self.utils.get_volume_element_name(volume.id),
            openstack_name=volume.display_name,
            source_volid=volume.source_volid,
            rdf_group_no=rdf_group_no,
            target_name=target_name, remote_array=remote_array,
            target_device_id=target_device_id,
            rep_mode=rep_mode, replication_status=replication_status,
            rdf_group_label=rdf_group_label
        )
        volume_metadata = self.update_volume_info_metadata(
            datadict, self.version_dict)
        self.print_pretty_table(volume_metadata)

    @debug_required
    def capture_retype_info(
            self, volume, device_id, array, srp, target_slo,
            target_workload, target_sg_name, is_rep_enabled, rep_mode,
            is_compression_disabled):
        """Captures manage existing info in volume metadata

        :param volume_id: volume identifier
        :param volume_size: volume size
        :param device_id: the PowerMax/VMAX device id
        :param array: the PowerMax/VMAX serialnumber
        :param srp: PowerMax/VMAX SRP
        :param target_slo: volume name
        :param target_workload: the PowerMax/VMAX device id
        :param is_rep_enabled: replication enabled flag
        :param rep_mode: replication mode
        :param is_compression_disabled: compression disabled flag
        """
        successful_operation = "retype"
        datadict = self.gather_volume_info(
            volume.id, successful_operation, False, volume_size=volume.size,
            device_id=device_id,
            target_sg_name=target_sg_name,
            serial_number=array,
            target_service_level=target_slo,
            target_workload=target_workload,
            srp=srp,
            identifier_name=self.utils.get_volume_element_name(volume.id),
            openstack_name=volume.display_name,
            is_rep_enabled=('yes' if is_rep_enabled else 'no'),
            rep_mode=rep_mode, is_compression_disabled=(
                'yes' if is_compression_disabled else 'no')
        )
        volume_metadata = self.update_volume_info_metadata(
            datadict, self.version_dict)
        self.print_pretty_table(volume_metadata)

    @debug_required
    def capture_delete_info(self, volume):
        """Captures delete info in volume metadata

        :param volume: the volume object
        """
        datadict = self.gather_volume_info(
            volume.id, 'delete', False,
            identifier_name=self.utils.get_volume_element_name(volume.id),
            openstack_name=volume.display_name)
        volume_metadata = self.update_volume_info_metadata(
            datadict, self.version_dict)
        self.print_pretty_table(volume_metadata)
