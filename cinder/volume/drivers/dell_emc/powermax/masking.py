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
import sys
import time

from oslo_log import log as logging
import re
import six

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.dell_emc.powermax import provision
from cinder.volume.drivers.dell_emc.powermax import utils
from cinder.volume import utils as volume_utils

LOG = logging.getLogger(__name__)

CREATE_IG_ERROR = "is already in use in another Initiator Group"


class PowerMaxMasking(object):
    """Masking class for Dell EMC PowerMax.

    Masking code to dynamically create a masking view.
    It supports VMAX 3, All Flash and PowerMax arrays.
    """
    def __init__(self, prtcl, rest):
        self.protocol = prtcl
        self.utils = utils.PowerMaxUtils()
        self.rest = rest
        self.provision = provision.PowerMaxProvision(self.rest)

    def setup_masking_view(
            self, serial_number, volume, masking_view_dict, extra_specs):

        @coordination.synchronized("emc-mv-{maskingview_name}")
        def do_get_or_create_masking_view_and_map_lun(maskingview_name):
            return self.get_or_create_masking_view_and_map_lun(
                serial_number, volume, maskingview_name, masking_view_dict,
                extra_specs)
        return do_get_or_create_masking_view_and_map_lun(
            masking_view_dict[utils.MV_NAME])

    def get_or_create_masking_view_and_map_lun(
            self, serial_number, volume, maskingview_name, masking_view_dict,
            extra_specs):
        """Get or Create a masking view and add a volume to the storage group.

        Given a masking view dict either get or create a masking view and add
        the volume to the associated storage group.
        :param serial_number: the array serial number
        :param volume: the volume object
        :param maskingview_name: the masking view name
        :param masking_view_dict: the masking view dict
        :param extra_specs: the extra specifications
        :returns: rollback_dict
        :raises: VolumeBackendAPIException
        """
        storagegroup_name = masking_view_dict[utils.SG_NAME]
        volume_name = masking_view_dict[utils.VOL_NAME]
        masking_view_dict[utils.EXTRA_SPECS] = extra_specs
        device_id = masking_view_dict[utils.DEVICE_ID]
        rep_mode = extra_specs.get(utils.REP_MODE, None)
        default_sg_name = self.utils.get_default_storage_group_name(
            masking_view_dict[utils.SRP],
            masking_view_dict[utils.SLO],
            masking_view_dict[utils.WORKLOAD],
            masking_view_dict[utils.DISABLECOMPRESSION],
            masking_view_dict[utils.IS_RE], rep_mode)
        rollback_dict = masking_view_dict

        try:
            error_message = self._get_or_create_masking_view(
                serial_number, masking_view_dict,
                default_sg_name, extra_specs)
            LOG.debug(
                "The masking view in the attach operation is "
                "%(masking_name)s. The storage group "
                "in the masking view is %(storage_name)s.",
                {'masking_name': maskingview_name,
                 'storage_name': storagegroup_name})
            rollback_dict['portgroup_name'] = (
                self.rest.get_element_from_masking_view(
                    serial_number, maskingview_name, portgroup=True))

        except Exception as e:
            LOG.exception(
                "Masking View creation or retrieval was not successful "
                "for masking view %(maskingview_name)s. "
                "Attempting rollback.",
                {'maskingview_name': masking_view_dict[utils.MV_NAME]})
            error_message = six.text_type(e)

        rollback_dict['default_sg_name'] = default_sg_name

        if error_message:
            # Rollback code if we cannot complete any of the steps above
            # successfully then we must roll back by adding the volume back to
            # the default storage group for that slo/workload combination.

            self.check_if_rollback_action_for_masking_required(
                serial_number, volume, device_id, rollback_dict)

            exception_message = (_(
                "Failed to get, create or add volume %(volumeName)s "
                "to masking view %(maskingview_name)s. "
                "The error message received was %(errorMessage)s.")
                % {'maskingview_name': maskingview_name,
                   'volumeName': volume_name,
                   'errorMessage': error_message})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        return rollback_dict

    def _move_vol_from_default_sg(
            self, serial_number, device_id, volume_name,
            default_sg_name, dest_storagegroup, extra_specs):
        """Get the default storage group and move the volume.

        :param serial_number: the array serial number
        :param device_id: the device id
        :param volume_name: the volume name
        :param default_sg_name: the name of the default sg
        :param dest_storagegroup: the destination storage group
        :param extra_specs: the extra specifications
        :returns: msg
        """
        msg = None
        check_vol = self.rest.is_volume_in_storagegroup(
            serial_number, device_id, default_sg_name)
        if check_vol:
            try:
                self.move_volume_between_storage_groups(
                    serial_number, device_id, default_sg_name,
                    dest_storagegroup, extra_specs)
            except Exception as e:
                msg = ("Exception while moving volume from the default "
                       "storage group to %(sg)s. Exception received was "
                       "%(e)s")
                LOG.error(msg, {'sg': dest_storagegroup, 'e': e})
        else:
            LOG.warning(
                "Volume: %(volume_name)s does not belong "
                "to default storage group %(default_sg_name)s.",
                {'volume_name': volume_name,
                 'default_sg_name': default_sg_name})
            msg = self._check_adding_volume_to_storage_group(
                serial_number, device_id, dest_storagegroup,
                volume_name, extra_specs)

        return msg

    def _get_or_create_masking_view(self, serial_number, masking_view_dict,
                                    default_sg_name, extra_specs):
        """Retrieve an existing masking view or create a new one.

        :param serial_number: the array serial number
        :param masking_view_dict: the masking view dict
        :param default_sg_name: the name of the default sg
        :param extra_specs: the extra specifications
        :returns: error message
        """
        maskingview_name = masking_view_dict[utils.MV_NAME]

        masking_view_details = self.rest.get_masking_view(
            serial_number, masking_view_name=maskingview_name)
        if not masking_view_details:
            self._sanity_port_group_check(
                masking_view_dict[utils.PORTGROUPNAME], serial_number)

            error_message = self._create_new_masking_view(
                serial_number, masking_view_dict, maskingview_name,
                default_sg_name, extra_specs)

        else:
            storagegroup_name, error_message = (
                self._validate_existing_masking_view(
                    serial_number, masking_view_dict, maskingview_name,
                    default_sg_name, extra_specs))

        return error_message

    def _sanity_port_group_check(self, port_group_name, serial_number):
        """Check if the port group exists

        :param port_group_name: the port group name (can be None)
        :param serial_number: the array serial number
        """
        exc_msg = None
        if port_group_name:
            portgroup = self.rest.get_portgroup(
                serial_number, port_group_name)
            if not portgroup:
                exc_msg = ("Failed to get portgroup %(pg)s."
                           % {'pg': port_group_name})
        else:
            exc_msg = "Port group cannot be left empty."
        if exc_msg:
            exception_message = (_(
                "%(exc_msg)s You must supply a valid pre-created "
                "port group in cinder.conf or as an extra spec.")
                % {'exc_msg': exc_msg})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

    def _create_new_masking_view(
            self, serial_number, masking_view_dict,
            maskingview_name, default_sg_name, extra_specs):
        """Create a new masking view.

        :param serial_number: the array serial number
        :param masking_view_dict: the masking view dict
        :param maskingview_name: the masking view name
        :param default_sg_name: the name of the default sg
        :param extra_specs: the extra specifications
        :returns: error_message
        """
        init_group_name = masking_view_dict[utils.IG_NAME]
        parent_sg_name = masking_view_dict[utils.PARENT_SG_NAME]
        storagegroup_name = masking_view_dict[utils.SG_NAME]
        connector = masking_view_dict[utils.CONNECTOR]
        port_group_name = masking_view_dict[utils.PORTGROUPNAME]
        LOG.info("Port Group in masking view operation: %(port_group_name)s.",
                 {'port_group_name': port_group_name})

        init_group_name, error_message = (self._get_or_create_initiator_group(
            serial_number, init_group_name, connector, extra_specs))
        if error_message:
            return error_message

        # get or create parent sg
        error_message = self._get_or_create_storage_group(
            serial_number, masking_view_dict, parent_sg_name, extra_specs,
            parent=True)
        if error_message:
            return error_message

        # get or create child sg
        error_message = self._get_or_create_storage_group(
            serial_number, masking_view_dict, storagegroup_name, extra_specs)
        if error_message:
            return error_message

        # Only after the components of the MV have been validated,
        # move the volume from the default storage group to the
        # masking view storage group. This is necessary before
        # creating a new masking view.
        error_message = self._move_vol_from_default_sg(
            serial_number, masking_view_dict[utils.DEVICE_ID],
            masking_view_dict[utils.VOL_NAME], default_sg_name,
            storagegroup_name, extra_specs)
        if error_message:
            return error_message

        error_message = self._check_add_child_sg_to_parent_sg(
            serial_number, storagegroup_name, parent_sg_name,
            masking_view_dict[utils.EXTRA_SPECS])
        if error_message:
            return error_message

        error_message = (self.create_masking_view(
            serial_number, maskingview_name, parent_sg_name,
            port_group_name, init_group_name, extra_specs))

        return error_message

    def _validate_existing_masking_view(
            self, serial_number, masking_view_dict,
            maskingview_name, default_sg_name, extra_specs):
        """Validate the components of an existing masking view.

        :param serial_number: the array serial number
        :param masking_view_dict: the masking view dict
        :param maskingview_name: the amsking view name
        :param default_sg_name: the default sg name
        :param extra_specs: the extra specifications
        :returns: storage_group_name -- string, msg -- string
        """
        storage_group_name, msg = self._check_existing_storage_group(
            serial_number, maskingview_name, default_sg_name,
            masking_view_dict)
        if not msg:
            portgroup_name = self.rest.get_element_from_masking_view(
                serial_number, maskingview_name, portgroup=True)
            __, msg = self._check_port_group(
                serial_number, portgroup_name)
            if not msg:
                initiator_group, msg = self._check_existing_initiator_group(
                    serial_number, maskingview_name, masking_view_dict,
                    storage_group_name, portgroup_name, extra_specs)

        return storage_group_name, msg

    def _check_add_child_sg_to_parent_sg(
            self, serial_number, child_sg_name, parent_sg_name, extra_specs):
        """Check adding a child storage group to a parent storage group.

        :param serial_number: the array serial number
        :param child_sg_name: the name of the child storage group
        :param parent_sg_name: the name of the aprent storage group
        :param extra_specs: the extra specifications
        :returns: error_message or None
        """
        msg = None
        if self.rest.is_child_sg_in_parent_sg(
                serial_number, child_sg_name, parent_sg_name):
            LOG.info("Child sg: %(child_sg)s is already part "
                     "of parent storage group %(parent_sg)s.",
                     {'child_sg': child_sg_name,
                      'parent_sg': parent_sg_name})
        else:
            try:
                self.add_child_sg_to_parent_sg(
                    serial_number, child_sg_name, parent_sg_name, extra_specs)
            except Exception as e:
                msg = ("Exception adding child sg %(child_sg)s to "
                       "%(parent_sg)s. Exception received was %(e)s"
                       % {'child_sg': child_sg_name,
                          'parent_sg': parent_sg_name,
                          'e': six.text_type(e)})
                LOG.error(msg)
        return msg

    def add_child_sg_to_parent_sg(
            self, serial_number, child_sg_name, parent_sg_name, extra_specs):
        """Add a child storage group to a parent storage group.

        :param serial_number: the array serial number
        :param child_sg_name: the name of the child storage group
        :param parent_sg_name: the name of the aprent storage group
        :param extra_specs: the extra specifications
        """
        start_time = time.time()

        @coordination.synchronized("emc-sg-{child_sg}")
        @coordination.synchronized("emc-sg-{parent_sg}")
        def do_add_sg_to_sg(child_sg, parent_sg):
            # Check if another process has added the child to the
            # parent sg while this process was waiting for the lock
            if self.rest.is_child_sg_in_parent_sg(
                    serial_number, child_sg_name, parent_sg_name):
                pass
            else:
                self.rest.add_child_sg_to_parent_sg(
                    serial_number, child_sg, parent_sg, extra_specs)

        do_add_sg_to_sg(child_sg_name, parent_sg_name)

        LOG.debug("Add child to storagegroup took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(start_time,
                                                      time.time())})
        LOG.info("Added child sg: %(child_name)s to parent storage "
                 "group %(parent_name)s.",
                 {'child_name': child_sg_name, 'parent_name': parent_sg_name})

    def _get_or_create_storage_group(
            self, serial_number, masking_view_dict, storagegroup_name,
            extra_specs, parent=False):
        """Get or create a storage group for a masking view.

        :param serial_number: the array serial number
        :param masking_view_dict: the masking view dict
        :param storagegroup_name: the storage group name
        :param extra_specs: the extra specifications
        :param parent: flag to indicate if this a parent storage group
        :returns: msg -- string or None
        """
        msg = None
        srp = extra_specs[utils.SRP]
        workload = extra_specs[utils.WORKLOAD]
        if parent:
            slo = None
        else:
            slo = extra_specs[utils.SLO]
        do_disable_compression = (
            masking_view_dict[utils.DISABLECOMPRESSION])
        storagegroup = self.rest.get_storage_group(
            serial_number, storagegroup_name)
        if storagegroup is None:
            storagegroup = self.provision.create_storage_group(
                serial_number, storagegroup_name, srp, slo, workload,
                extra_specs, do_disable_compression)

        if storagegroup is None:
            msg = ("Cannot get or create a storage group: "
                   "%(storagegroup_name)s for volume %(volume_name)s."
                   % {'storagegroup_name': storagegroup_name,
                      'volume_name': masking_view_dict[utils.VOL_NAME]})
            LOG.error(msg)

        # If qos exists, update storage group to reflect qos parameters
        if 'qos' in extra_specs:
            self.rest.update_storagegroup_qos(
                serial_number, storagegroup_name, extra_specs)

        return msg

    def _check_existing_storage_group(
            self, serial_number, maskingview_name,
            default_sg_name, masking_view_dict):
        """Check if the masking view has the child storage group.

        Get the parent storage group associated with a masking view and check
        if the required child storage group is already a member. If not, get
        or create the child storage group.
        :param serial_number: the array serial number
        :param maskingview_name: the masking view name
        :param default_sg_name: the default sg name
        :param masking_view_dict: the masking view dict
        :returns: storage group name, msg
        """
        msg = None
        child_sg_name = masking_view_dict[utils.SG_NAME]

        sg_from_mv = self.rest.get_element_from_masking_view(
            serial_number, maskingview_name, storagegroup=True)

        storagegroup = self.rest.get_storage_group(serial_number, sg_from_mv)

        if not storagegroup:
            msg = ("Cannot get storage group: %(sg_from_mv)s "
                   "from masking view %(masking_view)s."
                   % {'sg_from_mv': sg_from_mv,
                      'masking_view': maskingview_name})
            LOG.error(msg)
        else:
            check_child = self.rest.is_child_sg_in_parent_sg(
                serial_number, child_sg_name, sg_from_mv)
            child_sg = self.rest.get_storage_group(
                serial_number, child_sg_name)
            # Ensure the child sg can be retrieved
            if check_child and not child_sg:
                msg = ("Cannot get child storage group: %(sg_name)s "
                       "but it is listed as child of %(parent_sg)s"
                       % {'sg_name': child_sg_name, 'parent_sg': sg_from_mv})
                LOG.error(msg)
            elif check_child and child_sg:
                LOG.info("Retrieved child sg %(sg_name)s from %(mv_name)s",
                         {'sg_name': child_sg_name,
                          'mv_name': maskingview_name})
            else:
                msg = self._get_or_create_storage_group(
                    serial_number, masking_view_dict, child_sg_name,
                    masking_view_dict[utils.EXTRA_SPECS])
            if not msg:
                msg = self._move_vol_from_default_sg(
                    serial_number, masking_view_dict[utils.DEVICE_ID],
                    masking_view_dict[utils.VOL_NAME], default_sg_name,
                    child_sg_name, masking_view_dict[utils.EXTRA_SPECS])
            if not msg and not check_child:
                msg = self._check_add_child_sg_to_parent_sg(
                    serial_number, child_sg_name, sg_from_mv,
                    masking_view_dict[utils.EXTRA_SPECS])

        return child_sg_name, msg

    @coordination.synchronized("emc-sg-{source_storagegroup_name}")
    @coordination.synchronized("emc-sg-{target_storagegroup_name}")
    def move_volume_between_storage_groups(
            self, serial_number, device_id, source_storagegroup_name,
            target_storagegroup_name, extra_specs):
        """Move a volume between storage groups.

        :param serial_number: the array serial number
        :param device_id: the device id
        :param source_storagegroup_name: the source sg
        :param target_storagegroup_name: the target sg
        :param extra_specs: the extra specifications
        """
        num_vol_in_sg = self.rest.get_num_vols_in_sg(
            serial_number, source_storagegroup_name)
        LOG.debug("There are %(num_vol)d volumes in the "
                  "storage group %(sg_name)s.",
                  {'num_vol': num_vol_in_sg,
                   'sg_name': source_storagegroup_name})
        self.rest.move_volume_between_storage_groups(
            serial_number, device_id, source_storagegroup_name,
            target_storagegroup_name, extra_specs)
        if num_vol_in_sg == 1:
            # Check if storage group is a child sg
            parent_sg_name = self.get_parent_sg_from_child(
                serial_number, source_storagegroup_name)
            if parent_sg_name:
                self.rest.remove_child_sg_from_parent_sg(
                    serial_number, source_storagegroup_name, parent_sg_name,
                    extra_specs)
            # Last volume in the storage group - delete sg.
            self.rest.delete_storage_group(
                serial_number, source_storagegroup_name)

    def _check_port_group(self, serial_number, portgroup_name):
        """Check that you can get a port group.

        :param serial_number: the array serial number
        :param portgroup_name: the port group name
        :returns: string -- msg, the error message
        """
        msg = None
        portgroup = self.rest.get_portgroup(serial_number, portgroup_name)
        if portgroup is None:
            msg = ("Cannot get port group: %(portgroup)s from the array "
                   "%(array)s. Portgroups must be pre-configured - please "
                   "check the array."
                   % {'portgroup': portgroup_name, 'array': serial_number})
            LOG.error(msg)
        return portgroup_name, msg

    def _get_or_create_initiator_group(
            self, serial_number, init_group_name, connector, extra_specs):
        """Retrieve or create an initiator group.

        :param serial_number: the array serial number
        :param init_group_name: the name of the initiator group
        :param connector: the connector object
        :param extra_specs: the extra specifications
        :returns: name of the initiator group -- string, msg
        """
        msg = None
        initiator_names = self.find_initiator_names(connector)
        LOG.debug("The initiator name(s) are: %(initiatorNames)s.",
                  {'initiatorNames': initiator_names})

        found_init_group = self._find_initiator_group(
            serial_number, initiator_names)

        # If you cannot find an initiator group that matches the connector
        # info, create a new initiator group.
        if found_init_group is None:
            found_init_group = self._create_initiator_group(
                serial_number, init_group_name, initiator_names, extra_specs)
            LOG.info("Created new initiator group name: %(init_group_name)s.",
                     {'init_group_name': init_group_name})
        else:
            LOG.info("Using existing initiator group name: "
                     "%(init_group_name)s.",
                     {'init_group_name': found_init_group})

        if found_init_group is None:
            msg = ("Cannot get or create initiator group: "
                   "%(init_group_name)s. "
                   % {'init_group_name': init_group_name})
            LOG.error(msg)

        return found_init_group, msg

    def _check_existing_initiator_group(
            self, serial_number, maskingview_name, masking_view_dict,
            storagegroup_name, portgroup_name, extra_specs):
        """Checks an existing initiator group in the masking view.

        Check if the initiators in the initiator group match those in the
        system.
        :param serial_number: the array serial number
        :param maskingview_name: name of the masking view
        :param masking_view_dict: masking view dict
        :param storagegroup_name: the storage group name
        :param portgroup_name: the port group name
        :param extra_specs: the extra specifications
        :returns: ig_from_mv, msg
        """
        msg = None
        ig_from_mv = self.rest.get_element_from_masking_view(
            serial_number, maskingview_name, host=True)
        check_ig = masking_view_dict[utils.INITIATOR_CHECK]

        if check_ig:
            # First verify that the initiator group matches the initiators.
            check, found_ig = self._verify_initiator_group_from_masking_view(
                serial_number, maskingview_name, masking_view_dict, ig_from_mv,
                storagegroup_name, portgroup_name, extra_specs)
            if not check:
                msg = ("Unable to verify initiator group: %(ig_name)s "
                       "in masking view %(maskingview_name)s."
                       % {'ig_name': ig_from_mv,
                          'maskingview_name': maskingview_name})
                LOG.error(msg)
        return ig_from_mv, msg

    def _check_adding_volume_to_storage_group(
            self, serial_number, device_id, storagegroup_name,
            volume_name, extra_specs):
        """Check if a volume is part of an sg and add it if not.

        :param serial_number: the array serial number
        :param device_id: the device id
        :param storagegroup_name: the storage group name
        :param volume_name: volume name
        :param extra_specs: extra specifications
        :returns: msg
        """
        msg = None
        if self.rest.is_volume_in_storagegroup(
                serial_number, device_id, storagegroup_name):
            LOG.info("Volume: %(volume_name)s is already part "
                     "of storage group %(sg_name)s.",
                     {'volume_name': volume_name,
                      'sg_name': storagegroup_name})
        else:
            try:
                self.add_volume_to_storage_group(
                    serial_number, device_id, storagegroup_name,
                    volume_name, extra_specs)
            except Exception as e:
                msg = ("Exception adding volume %(vol)s to %(sg)s. "
                       "Exception received was %(e)s."
                       % {'vol': volume_name, 'sg': storagegroup_name,
                          'e': six.text_type(e)})
                LOG.error(msg)
        return msg

    def add_volume_to_storage_group(
            self, serial_number, device_id, storagegroup_name,
            volume_name, extra_specs):
        """Add a volume to a storage group.

        :param serial_number: array serial number
        :param device_id: volume device id
        :param storagegroup_name: storage group name
        :param volume_name: volume name
        :param extra_specs: extra specifications
        """
        start_time = time.time()

        @coordination.synchronized("emc-sg-{sg_name}")
        def do_add_volume_to_sg(sg_name):
            # Check if another process has added the volume to the
            # sg while this process was waiting for the lock
            if self.rest.is_volume_in_storagegroup(
                    serial_number, device_id, storagegroup_name):
                LOG.info("Volume: %(volume_name)s is already part "
                         "of storage group %(sg_name)s.",
                         {'volume_name': volume_name,
                          'sg_name': storagegroup_name})
            else:
                self.rest.add_vol_to_sg(serial_number, sg_name,
                                        device_id, extra_specs)
        do_add_volume_to_sg(storagegroup_name)

        LOG.debug("Add volume to storagegroup took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(start_time,
                                                      time.time())})
        LOG.info("Added volume: %(vol_name)s to storage group %(sg_name)s.",
                 {'vol_name': volume_name, 'sg_name': storagegroup_name})

    def add_volumes_to_storage_group(
            self, serial_number, list_device_id, storagegroup_name,
            extra_specs):
        """Add a volume to a storage group.

        :param serial_number: array serial number
        :param list_device_id: list of volume device id
        :param storagegroup_name: storage group name
        :param extra_specs: extra specifications
        """
        if not list_device_id:
            LOG.info("add_volumes_to_storage_group: No volumes to add")
            return
        start_time = time.time()
        temp_device_id_list = list_device_id

        @coordination.synchronized("emc-sg-{sg_name}")
        def do_add_volume_to_sg(sg_name):
            # Check if another process has added any volume to the
            # sg while this process was waiting for the lock
            volume_list = self.rest.get_volumes_in_storage_group(
                serial_number, storagegroup_name)
            for volume in volume_list:
                if volume in temp_device_id_list:
                    LOG.info("Volume: %(volume_name)s is already part "
                             "of storage group %(sg_name)s.",
                             {'volume_name': volume,
                              'sg_name': storagegroup_name})
                    # Remove this device id from the list
                    temp_device_id_list.remove(volume)
            self.rest.add_vol_to_sg(serial_number, storagegroup_name,
                                    temp_device_id_list, extra_specs)
        do_add_volume_to_sg(storagegroup_name)

        LOG.debug("Add volumes to storagegroup took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(start_time,
                                                      time.time())})
        LOG.info("Added volumes to storage group %(sg_name)s.",
                 {'sg_name': storagegroup_name})

    def remove_vol_from_storage_group(
            self, serial_number, device_id, storagegroup_name,
            volume_name, extra_specs):
        """Remove a volume from a storage group.

        :param serial_number: the array serial number
        :param device_id: the volume device id
        :param storagegroup_name: the name of the storage group
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        :raises: VolumeBackendAPIException
        """
        start_time = time.time()

        self.rest.remove_vol_from_sg(
            serial_number, storagegroup_name, device_id, extra_specs)

        LOG.debug("Remove volume from storagegroup took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(start_time,
                                                      time.time())})

        check_vol = (self.rest.is_volume_in_storagegroup(
            serial_number, device_id, storagegroup_name))
        if check_vol:
            exception_message = (_(
                "Failed to remove volume %(vol)s from SG: %(sg_name)s.")
                % {'vol': volume_name, 'sg_name': storagegroup_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)

    def remove_volumes_from_storage_group(
            self, serial_number, list_of_device_ids,
            storagegroup_name, extra_specs):
        """Remove multiple volumes from a storage group.

        :param serial_number: the array serial number
        :param list_of_device_ids: list of device ids
        :param storagegroup_name: the name of the storage group
        :param extra_specs: the extra specifications
        :raises: VolumeBackendAPIException
        """
        start_time = time.time()

        @coordination.synchronized("emc-sg-{sg_name}")
        def do_remove_volumes_from_storage_group(sg_name):
            self.rest.remove_vol_from_sg(
                serial_number, storagegroup_name,
                list_of_device_ids, extra_specs)

            LOG.debug("Remove volumes from storagegroup "
                      "took: %(delta)s H:MM:SS.",
                      {'delta': self.utils.get_time_delta(start_time,
                                                          time.time())})
            volume_list = self.rest.get_volumes_in_storage_group(
                serial_number, storagegroup_name)

            for device_id in list_of_device_ids:
                if device_id in volume_list:
                    exception_message = (_(
                        "Failed to remove device "
                        "with id %(dev_id)s from SG: %(sg_name)s.")
                        % {'dev_id': device_id, 'sg_name': storagegroup_name})
                    LOG.error(exception_message)
                    raise exception.VolumeBackendAPIException(
                        message=exception_message)
        return do_remove_volumes_from_storage_group(storagegroup_name)

    def find_initiator_names(self, connector):
        """Check the connector object for initiators(ISCSI) or wwpns(FC).

        :param connector: the connector object
        :returns: list -- list of found initiator names
        :raises: VolumeBackendAPIException
        """
        foundinitiatornames = []
        name = 'initiator name'
        if self.protocol.lower() == utils.ISCSI and connector['initiator']:
            foundinitiatornames.append(connector['initiator'])
        elif self.protocol.lower() == utils.FC:
            if 'wwpns' in connector and connector['wwpns']:
                for wwn in connector['wwpns']:
                    foundinitiatornames.append(wwn)
                name = 'world wide port names'
            else:
                msg = (_("FC is the protocol but wwpns are "
                         "not supplied by OpenStack."))
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(message=msg)

        if not foundinitiatornames:
            msg = (_("Error finding %(name)s.") % {'name': name})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(message=msg)

        LOG.debug("Found %(name)s: %(initiator)s.",
                  {'name': name,
                   'initiator': foundinitiatornames})

        return foundinitiatornames

    def _find_initiator_group(self, serial_number, initiator_names):
        """Check to see if an initiator group already exists.

        NOTE:  An initiator/wwn can only belong to one initiator group.
        If we were to attempt to create one with an initiator/wwn that is
        already belonging to another initiator group, it would fail.
        :param serial_number: the array serial number
        :param initiator_names: the list of initiator names
        :returns: initiator group name -- string or None
        """
        ig_name = None
        for initiator in initiator_names:
            params = {'initiator_hba': initiator.lower()}
            found_init = self.rest.get_initiator_list(serial_number, params)
            if found_init:
                ig_name = self.rest.get_initiator_group_from_initiator(
                    serial_number, found_init[0])
                break
        return ig_name

    def create_masking_view(
            self, serial_number, maskingview_name, storagegroup_name,
            port_group_name, init_group_name, extra_specs):
        """Create a new masking view.

        :param serial_number: the array serial number
        :param maskingview_name: the masking view name
        :param storagegroup_name: the storage group name
        :param port_group_name: the port group
        :param init_group_name: the initiator group
        :param extra_specs: extra specifications
        :returns: error_message -- string or None
        """
        error_message = None
        try:
            self.rest.create_masking_view(
                serial_number, maskingview_name, storagegroup_name,
                port_group_name, init_group_name, extra_specs)

        except Exception as e:
            error_message = ("Error creating new masking view. Exception "
                             "received: %(e)s" % {'e': six.text_type(e)})
        return error_message

    def check_if_rollback_action_for_masking_required(
            self, serial_number, volume, device_id, rollback_dict):
        """Rollback action for volumes with an associated service level.

        We need to be able to return the volume to its previous storage group
        if anything has gone wrong. We also may need to clean up any unused
        initiator groups.
        :param serial_number: the array serial number
        :param volume: the volume object
        :param device_id: the device id
        :param rollback_dict: the rollback dict
        :raises: VolumeBackendAPIException
        """
        reset = False if rollback_dict[utils.IS_MULTIATTACH] else True
        # Check if ig has been created. If so, check for other
        # masking views associated with the ig. If none, delete the ig.
        self._check_ig_rollback(
            serial_number, rollback_dict[utils.IG_NAME],
            rollback_dict[utils.CONNECTOR])
        try:
            # Remove it from the storage group associated with the connector,
            # if any. If not multiattach case, return to the default sg.
            self.remove_and_reset_members(
                serial_number, volume, device_id,
                rollback_dict[utils.VOL_NAME],
                rollback_dict[utils.EXTRA_SPECS], reset,
                rollback_dict[utils.CONNECTOR])
            if rollback_dict[utils.IS_MULTIATTACH]:
                # Move from the nonfast storage group to the fast sg
                if rollback_dict[utils.SLO] is not None:
                    self._return_volume_to_fast_managed_group(
                        serial_number, device_id,
                        rollback_dict[utils.OTHER_PARENT_SG],
                        rollback_dict[utils.FAST_SG],
                        rollback_dict[utils.NO_SLO_SG],
                        rollback_dict[utils.EXTRA_SPECS])
        except Exception as e:
            error_message = (_(
                "Rollback for Volume: %(volume_name)s has failed. "
                "Please contact your system administrator to manually return "
                "your volume to the default storage group for its slo. "
                "Exception received: %(e)s")
                % {'volume_name': rollback_dict['volume_name'],
                   'e': six.text_type(e)})
            LOG.exception(error_message)
            raise exception.VolumeBackendAPIException(message=error_message)

    def _verify_initiator_group_from_masking_view(
            self, serial_number, maskingview_name, maskingview_dict,
            ig_from_mv, storagegroup_name, portgroup_name, extra_specs):
        """Check that the initiator group contains the correct initiators.

        If using an existing masking view check that the initiator group
        contains the correct initiators.  If it does not contain the correct
        initiators then we delete the initiator group from the masking view,
        re-create it with the correct initiators and add it to the masking view
        NOTE:  PowerMax/VMAX does not support ModifyMaskingView so we must
               first delete the masking view and recreate it.
        :param serial_number: the array serial number
        :param maskingview_name: name of the masking view
        :param maskingview_dict: the masking view dict
        :param ig_from_mv: the initiator group name
        :param storagegroup_name: the storage group
        :param portgroup_name: the port group
        :param extra_specs: extra specifications
        :returns: bool, found_ig_from_connector
        """
        connector = maskingview_dict['connector']
        initiator_names = self.find_initiator_names(connector)
        found_ig_from_connector = self._find_initiator_group(
            serial_number, initiator_names)

        if found_ig_from_connector != ig_from_mv:
            check_ig = self.rest.get_initiator_group(
                serial_number, initiator_group=ig_from_mv)
            if check_ig:
                if found_ig_from_connector is None:
                    # If the name of the current initiator group from the
                    # masking view matches the igGroupName supplied for the
                    # new group, the existing ig needs to be deleted before
                    # the new one with the correct initiators can be created.
                    if maskingview_dict['init_group_name'] == ig_from_mv:
                        # Masking view needs to be deleted before IG
                        # can be deleted.
                        self.rest.delete_masking_view(
                            serial_number, maskingview_name)
                        self.rest.delete_initiator_group(
                            serial_number, ig_from_mv)
                        found_ig_from_connector = (
                            self._create_initiator_group(
                                serial_number, ig_from_mv, initiator_names,
                                extra_specs))
                if (found_ig_from_connector is not None and
                        storagegroup_name is not None and
                        portgroup_name is not None):
                    # Existing masking view (if still on the array) needs
                    # to be deleted before a new one can be created.
                    try:
                        self.rest.delete_masking_view(
                            serial_number, maskingview_name)
                    except Exception:
                        pass
                    error_message = (
                        self.create_masking_view(
                            serial_number, maskingview_name, storagegroup_name,
                            portgroup_name,
                            maskingview_dict['init_group_name'],
                            extra_specs))
                    if not error_message:
                        LOG.debug(
                            "The old masking view has been replaced: "
                            "%(maskingview_name)s.",
                            {'maskingview_name': maskingview_name})
                else:
                    LOG.error(
                        "One of the components of the original masking view "
                        "%(maskingview_name)s cannot be retrieved so "
                        "please contact your system administrator to check "
                        "that the correct initiator(s) are part of masking.",
                        {'maskingview_name': maskingview_name})
                    return False
        return True, found_ig_from_connector

    def _create_initiator_group(
            self, serial_number, init_group_name, initiator_names,
            extra_specs):
        """Create a new initiator group.

        Given a list of initiators, create a new initiator group.
        :param serial_number: array serial number
        :param init_group_name: the name for the initiator group
        :param initiator_names: initaitor names
        :param extra_specs: the extra specifications
        :returns: the initiator group name
        """
        try:
            self.rest.create_initiator_group(
                serial_number, init_group_name, initiator_names, extra_specs)
        except exception.VolumeBackendAPIException as ex:
            if re.search(CREATE_IG_ERROR, ex.msg):
                LOG.error("It is probable that initiator(s) %(initiators)s "
                          "belong to an existing initiator group (host) "
                          "that is neither logged into the array or part "
                          "of a masking view and as such cannot be queried. "
                          "Please delete this initiator group (host) and "
                          "re-run the operation.",
                          {'initiators': initiator_names})
            raise exception.VolumeBackendAPIException(message=ex)
        return init_group_name

    def _check_ig_rollback(
            self, serial_number, init_group_name, connector, force=False):
        """Check if rollback action is required on an initiator group.

        If anything goes wrong on a masking view creation, we need to check if
        the process created a now-stale initiator group before failing, i.e.
        an initiator group a) matching the name used in the mv process and
        b) not associated with any other masking views.
        If a stale ig exists, delete the ig.
        :param serial_number: the array serial number
        :param init_group_name: the initiator group name
        :param connector: the connector object
        :param force: force a delete even if no entry in login table
        """
        initiator_names = self.find_initiator_names(connector)
        found_ig_name = self._find_initiator_group(
            serial_number, initiator_names)
        if found_ig_name:
            if found_ig_name == init_group_name:
                force = True
        if force:
            found_ig_name = init_group_name
            host = init_group_name.split("-")[1]
            LOG.debug("Searching for masking views associated with "
                      "%(init_group_name)s",
                      {'init_group_name': init_group_name})
            self._last_volume_delete_initiator_group(
                serial_number, found_ig_name, host)

    @coordination.synchronized("emc-vol-{device_id}")
    def remove_and_reset_members(
            self, serial_number, volume, device_id, volume_name,
            extra_specs, reset=True, connector=None, async_grp=None):
        """This is called on a delete, unmap device or rollback.

        :param serial_number: the array serial number
        :param volume: the volume object
        :param device_id: the volume device id
        :param volume_name: the volume name
        :param extra_specs: additional info
        :param reset: reset, return to original SG (optional)
        :param connector: the connector object (optional)
        :param async_grp: the async rep group (optional)
        """
        self._cleanup_deletion(
            serial_number, volume, device_id, volume_name,
            extra_specs, connector, reset, async_grp)

    def _cleanup_deletion(
            self, serial_number, volume, device_id, volume_name,
            extra_specs, connector, reset, async_grp):
        """Prepare a volume for a delete operation.

        :param serial_number: the array serial number
        :param volume: the volume object
        :param device_id: the volume device id
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        :param connector: the connector object
        :param reset: flag to indicate if reset is required -- bool
        :param async_grp: the async rep group
        """

        move = False
        short_host_name = None
        storagegroup_names = (self.rest.get_storage_groups_from_volume(
            serial_number, device_id))
        if storagegroup_names:
            if async_grp is not None:
                for index, sg in enumerate(storagegroup_names):
                    if sg == async_grp:
                        storagegroup_names.pop(index)
            if len(storagegroup_names) == 1 and reset is True:
                move = True
            elif connector is not None:
                short_host_name = self.utils.get_host_short_name(
                    connector['host'])
                move = reset
            if short_host_name:
                for sg_name in storagegroup_names:
                    if short_host_name in sg_name:
                        self.remove_volume_from_sg(
                            serial_number, device_id, volume_name, sg_name,
                            extra_specs, connector, move)
                        break
            else:
                for sg_name in storagegroup_names:
                    self.remove_volume_from_sg(
                        serial_number, device_id, volume_name, sg_name,
                        extra_specs, connector, move)
        if reset is True and move is False:
            self.add_volume_to_default_storage_group(
                serial_number, device_id, volume_name,
                extra_specs, volume=volume)

    def remove_volume_from_sg(
            self, serial_number, device_id, vol_name, storagegroup_name,
            extra_specs, connector=None, move=False):
        """Remove a volume from a storage group.

        :param serial_number: the array serial number
        :param device_id: the volume device id
        :param vol_name: the volume name
        :param storagegroup_name: the storage group name
        :param extra_specs: the extra specifications
        :param connector: the connector object
        :param move: flag to indicate if move should be used instead of remove
        """
        masking_list = self.rest.get_masking_views_from_storage_group(
            serial_number, storagegroup_name)
        if not masking_list:
            LOG.debug("No masking views associated with storage group "
                      "%(sg_name)s", {'sg_name': storagegroup_name})

            @coordination.synchronized("emc-sg-{sg_name}")
            def do_remove_volume_from_sg(sg_name):
                # Make sure volume hasn't been recently removed from the sg
                if self.rest.is_volume_in_storagegroup(
                        serial_number, device_id, sg_name):
                    num_vol_in_sg = self.rest.get_num_vols_in_sg(
                        serial_number, sg_name)
                    LOG.debug("There are %(num_vol)d volumes in the "
                              "storage group %(sg_name)s.",
                              {'num_vol': num_vol_in_sg,
                               'sg_name': sg_name})

                    if num_vol_in_sg == 1:
                        # Last volume in the storage group - delete sg.
                        self._last_vol_in_sg(
                            serial_number, device_id, vol_name, sg_name,
                            extra_specs, move)
                    else:
                        # Not the last volume so remove it from storage group
                        self._multiple_vols_in_sg(
                            serial_number, device_id, sg_name, vol_name,
                            extra_specs, move)
                else:
                    LOG.info("Volume with device_id %(dev)s is no longer a "
                             "member of %(sg)s.",
                             {'dev': device_id, 'sg': sg_name})

            return do_remove_volume_from_sg(storagegroup_name)
        else:
            # Need to lock masking view when we are locking the storage
            # group to avoid possible deadlock situations from concurrent
            # processes
            masking_name = masking_list[0]
            parent_sg_name = self.rest.get_element_from_masking_view(
                serial_number, masking_name, storagegroup=True)

            @coordination.synchronized("emc-mv-{parent_name}")
            @coordination.synchronized("emc-mv-{mv_name}")
            @coordination.synchronized("emc-sg-{sg_name}")
            def do_remove_volume_from_sg(mv_name, sg_name, parent_name):
                # Make sure volume hasn't been recently removed from the sg
                is_vol = self.rest.is_volume_in_storagegroup(
                    serial_number, device_id, sg_name)
                if is_vol:
                    num_vol_in_sg = self.rest.get_num_vols_in_sg(
                        serial_number, sg_name)
                    LOG.debug(
                        "There are %(num_vol)d volumes in the storage group "
                        "%(sg_name)s associated with %(mv_name)s. Parent "
                        "storagegroup is %(parent)s.",
                        {'num_vol': num_vol_in_sg, 'sg_name': sg_name,
                         'mv_name': mv_name, 'parent': parent_name})

                    if num_vol_in_sg == 1:
                        # Last volume in the storage group - delete sg.
                        self._last_vol_in_sg(
                            serial_number, device_id, vol_name, sg_name,
                            extra_specs, move, connector)
                    else:
                        # Not the last volume so remove it from storage group
                        self._multiple_vols_in_sg(
                            serial_number, device_id, sg_name, vol_name,
                            extra_specs, move)
                else:
                    LOG.info("Volume with device_id %(dev)s is no longer a "
                             "member of %(sg)s",
                             {'dev': device_id, 'sg': sg_name})

            return do_remove_volume_from_sg(masking_name, storagegroup_name,
                                            parent_sg_name)

    def _last_vol_in_sg(self, serial_number, device_id, volume_name,
                        storagegroup_name, extra_specs, move, connector=None):
        """Steps if the volume is the last in a storage group.

        1. Check if the volume is in a masking view.
        2. If it is in a masking view, check if it is the last volume in the
           masking view or just this child storage group.
        3. If it is last in the masking view, delete the masking view,
           delete the initiator group if there are no other masking views
           associated with it, and delete the both the current storage group
           and its parent group.
        4. Otherwise, remove the volume and delete the child storage group.
        5. If it is not in a masking view, delete the storage group.
        :param serial_number: array serial number
        :param device_id: volume device id
        :param volume_name: volume name
        :param storagegroup_name: storage group name
        :param extra_specs: extra specifications
        :param move: flag to indicate a move instead of remove
        :param connector: the connector object
        :returns: status -- bool
        """
        LOG.debug("Only one volume remains in storage group "
                  "%(sgname)s. Driver will attempt cleanup.",
                  {'sgname': storagegroup_name})
        maskingview_list = self.rest.get_masking_views_from_storage_group(
            serial_number, storagegroup_name)
        if not bool(maskingview_list):
            status = self._last_vol_no_masking_views(
                serial_number, storagegroup_name, device_id, volume_name,
                extra_specs, move)
        else:
            status = self._last_vol_masking_views(
                serial_number, storagegroup_name, maskingview_list,
                device_id, volume_name, extra_specs, connector, move)
        return status

    def _last_vol_no_masking_views(self, serial_number, storagegroup_name,
                                   device_id, volume_name, extra_specs, move):
        """Remove the last vol from an sg not associated with an mv.

        Helper function for removing the last vol from a storage group
        which is not associated with a masking view.
        :param serial_number: the array serial number
        :param storagegroup_name: the storage group name
        :param device_id: the device id
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        :param move: flag to indicate a move instead of remove
        :returns: status -- bool
        """
        # Check if storage group is a child sg:
        parent_sg = self.get_parent_sg_from_child(
            serial_number, storagegroup_name)
        if parent_sg is None:
            # Move the volume back to the default storage group, if required
            if move:
                self.add_volume_to_default_storage_group(
                    serial_number, device_id, volume_name,
                    extra_specs, src_sg=storagegroup_name)
            # Delete the storage group.
            self.rest.delete_storage_group(serial_number, storagegroup_name)
            status = True
        else:
            num_vols_parent = self.rest.get_num_vols_in_sg(
                serial_number, parent_sg)
            if num_vols_parent == 1:
                self._delete_cascaded_storage_groups(
                    serial_number, storagegroup_name, parent_sg,
                    extra_specs, device_id, move)
            else:
                self._remove_last_vol_and_delete_sg(
                    serial_number, device_id, volume_name,
                    storagegroup_name, extra_specs, parent_sg, move)
            status = True
        return status

    def _last_vol_masking_views(
            self, serial_number, storagegroup_name, maskingview_list,
            device_id, volume_name, extra_specs, connector, move):
        """Remove the last vol from an sg associated with masking views.

        Helper function for removing the last vol from a storage group
        which is associated with one or more masking views.
        :param serial_number: the array serial number
        :param storagegroup_name: the storage group name
        :param maskingview_list: the liast of masking views
        :param device_id: the device id
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        :param move: flag to indicate a move instead of remove
        :returns: status -- bool
        """
        status = False
        for mv in maskingview_list:
            num_vols_in_mv, parent_sg_name = (
                self._get_num_vols_from_mv(serial_number, mv))
            # If the volume is the last in the masking view, full cleanup
            if num_vols_in_mv == 1:
                self._delete_mv_ig_and_sg(
                    serial_number, device_id, mv, storagegroup_name,
                    parent_sg_name, connector, move, extra_specs)
            else:
                self._remove_last_vol_and_delete_sg(
                    serial_number, device_id, volume_name,
                    storagegroup_name, extra_specs, parent_sg_name, move)
            status = True
        return status

    def get_parent_sg_from_child(self, serial_number, storagegroup_name):
        """Given a storage group name, get its parent storage group, if any.

        :param serial_number: the array serial number
        :param storagegroup_name: the name of the storage group
        :returns: the parent storage group name, or None
        """
        parent_sg_name = None
        storagegroup = self.rest.get_storage_group(
            serial_number, storagegroup_name)
        if storagegroup and storagegroup.get('parent_storage_group'):
            parent_sg_name = storagegroup['parent_storage_group'][0]
        return parent_sg_name

    def _get_num_vols_from_mv(self, serial_number, maskingview_name):
        """Get the total number of volumes associated with a masking view.

        :param serial_number: the array serial number
        :param maskingview_name: the name of the masking view
        :returns: num_vols, parent_sg_name
        """
        parent_sg_name = self.rest.get_element_from_masking_view(
            serial_number, maskingview_name, storagegroup=True)
        num_vols = self.rest.get_num_vols_in_sg(serial_number, parent_sg_name)
        return num_vols, parent_sg_name

    def _multiple_vols_in_sg(self, serial_number, device_id, storagegroup_name,
                             volume_name, extra_specs, move):
        """Remove the volume from the SG.

        If the volume is not the last in the storage group,
        remove the volume from the SG and leave the sg on the array.
        :param serial_number: array serial number
        :param device_id: volume device id
        :param volume_name: volume name
        :param storagegroup_name: storage group name
        :param move: flag to indicate a move instead of remove
        :param extra_specs: extra specifications
        """
        if move:
            self.add_volume_to_default_storage_group(
                serial_number, device_id, volume_name,
                extra_specs, src_sg=storagegroup_name)
        else:
            self.remove_vol_from_storage_group(
                serial_number, device_id, storagegroup_name,
                volume_name, extra_specs)

        LOG.debug(
            "Volume %(volume_name)s successfully moved/ removed from "
            "storage group %(sg)s.",
            {'volume_name': volume_name, 'sg': storagegroup_name})

        num_vol_in_sg = self.rest.get_num_vols_in_sg(
            serial_number, storagegroup_name)
        LOG.debug("There are %(num_vol)d volumes remaining in the storage "
                  "group %(sg_name)s.",
                  {'num_vol': num_vol_in_sg,
                   'sg_name': storagegroup_name})

    def _delete_cascaded_storage_groups(self, serial_number, child_sg_name,
                                        parent_sg_name, extra_specs,
                                        device_id, move):
        """Delete a child and parent storage groups.

        :param serial_number: the array serial number
        :param child_sg_name: the child storage group name
        :param parent_sg_name: the parent storage group name
        :param extra_specs: the extra specifications
        :param device_id: the volume device id
        :param move: flag to indicate if volume should be moved to default sg
        """
        if move:
            self.add_volume_to_default_storage_group(
                serial_number, device_id, "",
                extra_specs, src_sg=child_sg_name)
        if child_sg_name != parent_sg_name:
            self.rest.delete_storage_group(serial_number, parent_sg_name)
            LOG.debug("Storage Group %(storagegroup_name)s "
                      "successfully deleted.",
                      {'storagegroup_name': parent_sg_name})
        self.rest.delete_storage_group(serial_number, child_sg_name)

        LOG.debug("Storage Group %(storagegroup_name)s successfully deleted.",
                  {'storagegroup_name': child_sg_name})

    def _delete_mv_ig_and_sg(
            self, serial_number, device_id, masking_view, storagegroup_name,
            parent_sg_name, connector, move, extra_specs):
        """Delete the masking view, storage groups and initiator group.

        :param serial_number: array serial number
        :param device_id: the device id
        :param masking_view: masking view name
        :param storagegroup_name: storage group name
        :param parent_sg_name: the parent storage group name
        :param connector: the connector object
        :param move: flag to indicate if the volume should be moved
        :param extra_specs: the extra specifications
        """
        host = (self.utils.get_host_short_name(connector['host'])
                if connector else None)

        initiatorgroup = self.rest.get_element_from_masking_view(
            serial_number, masking_view, host=True)
        self._last_volume_delete_masking_view(serial_number, masking_view)
        self._last_volume_delete_initiator_group(
            serial_number, initiatorgroup, host)
        self._delete_cascaded_storage_groups(
            serial_number, storagegroup_name, parent_sg_name,
            extra_specs, device_id, move)

    def _last_volume_delete_masking_view(self, serial_number, masking_view):
        """Delete the masking view.

        Delete the masking view if the volume is the last one in the
        storage group.
        :param serial_number: the array serial number
        :param masking_view: masking view name
        """
        LOG.debug("Last volume in the storage group, deleting masking view "
                  "%(maskingview_name)s.", {'maskingview_name': masking_view})
        self.rest.delete_masking_view(serial_number, masking_view)
        LOG.info("Masking view %(maskingview)s successfully deleted.",
                 {'maskingview': masking_view})

    def add_volume_to_default_storage_group(
            self, serial_number, device_id, volume_name,
            extra_specs, src_sg=None, volume=None):
        """Return volume to its default storage group.

        :param serial_number: the array serial number
        :param device_id: the volume device id
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        :param src_sg: the source storage group, if any
        :param volume: the volume object
        """
        do_disable_compression = self.utils.is_compression_disabled(
            extra_specs)
        rep_enabled = self.utils.is_replication_enabled(extra_specs)
        rep_mode = extra_specs.get(utils.REP_MODE, None)
        if self.rest.is_next_gen_array(serial_number):
            extra_specs[utils.WORKLOAD] = 'NONE'
        storagegroup_name = self.get_or_create_default_storage_group(
            serial_number, extra_specs[utils.SRP], extra_specs[utils.SLO],
            extra_specs[utils.WORKLOAD], extra_specs, do_disable_compression,
            rep_enabled, rep_mode)
        if src_sg is not None:
            # Need to lock the default storage group
            @coordination.synchronized("emc-sg-{default_sg_name}")
            def _move_vol_to_default_sg(default_sg_name):
                self.rest.move_volume_between_storage_groups(
                    serial_number, device_id, src_sg,
                    default_sg_name, extra_specs, force=True)
            _move_vol_to_default_sg(storagegroup_name)
        else:
            self._check_adding_volume_to_storage_group(
                serial_number, device_id, storagegroup_name, volume_name,
                extra_specs)
        if volume:
            # Need to check if the volume needs to be returned to a
            # generic volume group. This may be necessary in a force-detach
            # situation.
            self.return_volume_to_volume_group(
                serial_number, volume, device_id, volume_name, extra_specs)

    def return_volume_to_volume_group(self, serial_number, volume,
                                      device_id, volume_name, extra_specs):
        """Return a volume to its volume group, if required.

        :param serial_number: the array serial number
        :param volume: the volume object
        :param device_id: the device id
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        """
        if (volume.group_id is not None and
                (volume_utils.is_group_a_cg_snapshot_type(volume.group)
                 or volume.group.is_replicated)):
            vol_grp_name = self.provision.get_or_create_volume_group(
                serial_number, volume.group, extra_specs)
            self._check_adding_volume_to_storage_group(
                serial_number, device_id,
                vol_grp_name, volume_name, extra_specs)
            if volume.group.is_replicated:
                self.add_remote_vols_to_volume_group(
                    volume, volume.group, extra_specs)

    def add_remote_vols_to_volume_group(
            self, volumes, group, extra_specs, rep_driver_data=None):
        """Add the remote volumes to their volume group.

        :param volumes: list of volumes
        :param group: the id of the group
        :param extra_specs: the extra specifications
        :param rep_driver_data: replication driver data, optional
        """
        remote_device_list = []
        remote_array = None
        if not isinstance(volumes, list):
            volumes = [volumes]
        for vol in volumes:
            try:
                remote_loc = ast.literal_eval(vol.replication_driver_data)
            except (ValueError, KeyError):
                remote_loc = ast.literal_eval(rep_driver_data)
            remote_array = remote_loc['array']
            founddevice_id = self.rest.check_volume_device_id(
                remote_array, remote_loc['device_id'], vol.id)
            if founddevice_id is not None:
                remote_device_list.append(founddevice_id)
        group_name = self.provision.get_or_create_volume_group(
            remote_array, group, extra_specs)
        self.add_volumes_to_storage_group(
            remote_array, remote_device_list, group_name, extra_specs)
        LOG.info("Added volumes to remote volume group.")

    def get_or_create_default_storage_group(
            self, serial_number, srp, slo, workload, extra_specs,
            do_disable_compression=False, is_re=False, rep_mode=None):
        """Get or create a default storage group.

        :param serial_number: the array serial number
        :param srp: the SRP name
        :param slo: the SLO
        :param workload: the workload
        :param extra_specs: extra specifications
        :param do_disable_compression: flag for compression
        :param is_re: is replication enabled
        :param rep_mode: flag to indicate replication mode
        :returns: storagegroup_name
        :raises: VolumeBackendAPIException
        """
        storagegroup, storagegroup_name = (
            self.rest.get_vmax_default_storage_group(
                serial_number, srp, slo, workload, do_disable_compression,
                is_re, rep_mode))
        if storagegroup is None:
            self.provision.create_storage_group(
                serial_number, storagegroup_name, srp, slo, workload,
                extra_specs, do_disable_compression)
        else:
            # Check that SG is not part of a masking view
            LOG.info("Using existing default storage group")
            masking_views = self.rest.get_masking_views_from_storage_group(
                serial_number, storagegroup_name)
            if masking_views:
                exception_message = (_(
                    "Default storage group %(sg_name)s is part of masking "
                    "views %(mvs)s. Please remove it from all masking views")
                    % {'sg_name': storagegroup_name, 'mvs': masking_views})
                LOG.error(exception_message)
                raise exception.VolumeBackendAPIException(
                    message=exception_message)
        # If qos exists, update storage group to reflect qos parameters
        if 'qos' in extra_specs:
            self.rest.update_storagegroup_qos(
                serial_number, storagegroup_name, extra_specs)

        return storagegroup_name

    def _remove_last_vol_and_delete_sg(
            self, serial_number, device_id, volume_name,
            storagegroup_name, extra_specs, parent_sg_name=None, move=False):
        """Remove the last volume and delete the storage group.

        If the storage group is a child of another storage group,
        it must be removed from the parent before deletion.
        :param serial_number: the array serial number
        :param device_id: the volume device id
        :param volume_name: the volume name
        :param storagegroup_name: the sg name
        :param extra_specs: extra specifications
        :param parent_sg_name: the parent sg name
        """
        if move:
            self.add_volume_to_default_storage_group(
                serial_number, device_id, volume_name,
                extra_specs, src_sg=storagegroup_name)
        else:
            self.remove_vol_from_storage_group(
                serial_number, device_id, storagegroup_name, volume_name,
                extra_specs)

        LOG.debug("Remove the last volume %(volumeName)s completed "
                  "successfully.", {'volumeName': volume_name})
        if parent_sg_name:
            self.rest.remove_child_sg_from_parent_sg(
                serial_number, storagegroup_name, parent_sg_name,
                extra_specs)

        self.rest.delete_storage_group(serial_number, storagegroup_name)

    def _last_volume_delete_initiator_group(
            self, serial_number, initiatorgroup_name, host):
        """Delete the initiator group.

        Delete the Initiator group if it has been created by the PowerMax
        driver, and if there are no masking views associated with it.
        :param serial_number: the array serial number
        :param initiatorgroup_name: initiator group name
        :param host: the short name of the host
        """
        if host is not None:
            protocol = self.utils.get_short_protocol_type(self.protocol)
            default_ig_name = ("OS-%(shortHostName)s-%(protocol)s-IG"
                               % {'shortHostName': host,
                                  'protocol': protocol})

            if initiatorgroup_name == default_ig_name:
                maskingview_names = (
                    self.rest.get_masking_views_by_initiator_group(
                        serial_number, initiatorgroup_name))
                if not maskingview_names:
                    @coordination.synchronized("emc-ig-{ig_name}")
                    def _delete_ig(ig_name):
                        # Check initiator group hasn't been recently deleted
                        ig_details = self.rest.get_initiator_group(
                            serial_number, ig_name)
                        if ig_details:
                            LOG.debug(
                                "Last volume associated with the initiator "
                                "group - deleting the associated initiator "
                                "group %(initiatorgroup_name)s.",
                                {'initiatorgroup_name': initiatorgroup_name})
                            self.rest.delete_initiator_group(
                                serial_number, initiatorgroup_name)
                    _delete_ig(initiatorgroup_name)
                else:
                    LOG.warning("Initiator group %(ig_name)s is associated "
                                "with masking views and can't be deleted. "
                                "Number of associated masking view is: "
                                "%(nmv)d.",
                                {'ig_name': initiatorgroup_name,
                                 'nmv': len(maskingview_names)})
            else:
                LOG.warning("Initiator group %(ig_name)s was "
                            "not created by the PowerMax driver so will "
                            "not be deleted by the PowerMax driver.",
                            {'ig_name': initiatorgroup_name})
        else:
            LOG.warning("Cannot get host name from connector object - "
                        "initiator group %(ig_name)s will not be deleted.",
                        {'ig_name': initiatorgroup_name})

    def pre_multiattach(self, serial_number, device_id, mv_dict, extra_specs):
        """Run before attaching a device to multiple hosts.

        :param serial_number: the array serial number
        :param device_id: the device id
        :param mv_dict: the masking view dict
        :param extra_specs: extra specifications
        :returns: masking view dict
        """
        no_slo_sg_name, fast_source_sg_name, parent_sg_name = None, None, None
        sg_list = self.rest.get_storage_group_list(
            serial_number, params={
                'child': 'true', 'volumeId': device_id})
        # You need to put in something here for legacy
        if not sg_list.get('storageGroupId'):
            storage_group_list = self.rest.get_storage_groups_from_volume(
                serial_number, device_id)
            if storage_group_list and len(storage_group_list) == 1:
                if 'STG-' in storage_group_list[0]:
                    return mv_dict

        split_pool = extra_specs['pool_name'].split('+')
        src_slo = split_pool[0]
        src_wl = split_pool[1] if len(split_pool) == 4 else 'NONE'
        slo_wl_combo = self.utils.truncate_string(src_slo + src_wl, 10)
        for sg in sg_list.get('storageGroupId', []):
            if slo_wl_combo in sg:
                fast_source_sg_name = sg
                masking_view_name = (
                    self.rest.get_masking_views_from_storage_group(
                        serial_number, fast_source_sg_name))[0]
                port_group_name = self.rest.get_element_from_masking_view(
                    serial_number, masking_view_name, portgroup=True)
                short_pg_name = self.utils.get_pg_short_name(port_group_name)
                short_host_name = masking_view_name.lstrip('OS-').rstrip(
                    '-%s-MV' % short_pg_name)[:-2]
                extra_specs[utils.PORTGROUPNAME] = short_pg_name
                no_slo_extra_specs = deepcopy(extra_specs)
                no_slo_extra_specs[utils.SLO] = None
                no_slo_sg_name, __, __, __ = self.utils.get_child_sg_name(
                    short_host_name, no_slo_extra_specs)
                source_sg_details = self.rest.get_storage_group(
                    serial_number, fast_source_sg_name)
                parent_sg_name = source_sg_details[
                    'parent_storage_group'][0]
                mv_dict[utils.OTHER_PARENT_SG] = parent_sg_name
                mv_dict[utils.FAST_SG] = fast_source_sg_name
                mv_dict[utils.NO_SLO_SG] = no_slo_sg_name
        try:
            no_slo_sg = self.rest.get_storage_group(
                serial_number, no_slo_sg_name)
            if no_slo_sg is None:
                self.provision.create_storage_group(
                    serial_number, no_slo_sg_name,
                    None, None, None, extra_specs)
            self._check_add_child_sg_to_parent_sg(
                serial_number, no_slo_sg_name, parent_sg_name, extra_specs)
            self.move_volume_between_storage_groups(
                serial_number, device_id, fast_source_sg_name,
                no_slo_sg_name, extra_specs)
            # Clean up the fast managed group, if required
            self._clean_up_child_storage_group(
                serial_number, fast_source_sg_name,
                parent_sg_name, extra_specs)
        except Exception:
            # Move it back to original storage group, if required
            self._return_volume_to_fast_managed_group(
                serial_number, device_id, parent_sg_name,
                fast_source_sg_name, no_slo_sg_name, extra_specs)
            exception_message = (_("Unable to setup for multiattach because "
                                   "of the following error: %(error_msg)s.")
                                 % {'error_msg': sys.exc_info()[1]})
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        return mv_dict

    def return_volume_to_fast_managed_group(
            self, serial_number, device_id, extra_specs):
        """Return a volume to a fast managed group if slo is set.

        On a detach on a multiattach volume, return the volume to its fast
        managed group, if slo is set.
        :param serial_number: the array serial number
        :param device_id: the device id
        :param extra_specs: the extra specifications
        """
        if extra_specs[utils.SLO]:
            # Get a parent storage group of the volume
            sg_list = self.rest.get_storage_group_list(
                serial_number, params={
                    'child': 'true', 'volumeId': device_id})
            slo_wl_combo = '-No_SLO-'
            for sg in sg_list.get('storageGroupId', []):
                if slo_wl_combo in sg:
                    no_slo_sg_name = sg
                    masking_view_name = (
                        self.rest.get_masking_views_from_storage_group(
                            serial_number, no_slo_sg_name))[0]
                    port_group_name = self.rest.get_element_from_masking_view(
                        serial_number, masking_view_name, portgroup=True)
                    short_pg_name = self.utils.get_pg_short_name(
                        port_group_name)
                    short_host_name = masking_view_name.lstrip('OS-').rstrip(
                        '-%s-MV' % short_pg_name)[:-2]
                    extra_specs[utils.PORTGROUPNAME] = short_pg_name
                    fast_sg_name, _, _, _ = self.utils.get_child_sg_name(
                        short_host_name, extra_specs)
                    source_sg_details = self.rest.get_storage_group(
                        serial_number, no_slo_sg_name)
                    parent_sg_name = source_sg_details[
                        'parent_storage_group'][0]
                    self._return_volume_to_fast_managed_group(
                        serial_number, device_id, parent_sg_name,
                        fast_sg_name, no_slo_sg_name, extra_specs)
                    break

    def _return_volume_to_fast_managed_group(
            self, serial_number, device_id, parent_sg_name,
            fast_sg_name, no_slo_sg_name, extra_specs):
        """Return a volume to its fast managed group.

        On a detach, or failed attach, on a multiattach volume, return the
        volume to its fast managed group, if required.
        :param serial_number: the array serial number
        :param device_id: the device id
        :param parent_sg_name: the parent sg name
        :param fast_sg_name: the fast managed sg name
        :param no_slo_sg_name: the no slo sg name
        :param extra_specs: the extra specifications
        """
        sg_list = self.rest.get_storage_groups_from_volume(
            serial_number, device_id)
        in_fast_sg = True if fast_sg_name in sg_list else False
        if in_fast_sg is False:
            disable_compr = self.utils.is_compression_disabled(extra_specs)
            mv_dict = {utils.DISABLECOMPRESSION: disable_compr,
                       utils.VOL_NAME: device_id}
            # Get or create the fast child sg
            self._get_or_create_storage_group(
                serial_number, mv_dict, fast_sg_name, extra_specs)
            # Add child sg to parent sg if required
            self.add_child_sg_to_parent_sg(
                serial_number, fast_sg_name, parent_sg_name, extra_specs)
            # Add or move volume to fast sg
            self._move_vol_from_default_sg(
                serial_number, device_id, device_id,
                no_slo_sg_name, fast_sg_name, extra_specs)
        else:
            LOG.debug("Volume already a member of the FAST managed storage "
                      "group.")
            # Check if non-fast storage group needs to be cleaned up
            self._clean_up_child_storage_group(
                serial_number, no_slo_sg_name, parent_sg_name, extra_specs)

    def _clean_up_child_storage_group(self, serial_number, child_sg_name,
                                      parent_sg_name, extra_specs):
        """Clean up an empty child storage group, if required.

        :param serial_number: the array serial number
        :param child_sg_name: the child storage group
        :param parent_sg_name: the parent storage group
        :param extra_specs: extra specifications
        """
        child_sg = self.rest.get_storage_group(serial_number, child_sg_name)
        if child_sg:
            num_vol_in_sg = self.rest.get_num_vols_in_sg(
                serial_number, child_sg_name)
            if num_vol_in_sg == 0:
                if self.rest.is_child_sg_in_parent_sg(
                        serial_number, child_sg_name, parent_sg_name):
                    self.rest.remove_child_sg_from_parent_sg(
                        serial_number, child_sg_name,
                        parent_sg_name, extra_specs)
                self.rest.delete_storage_group(
                    serial_number, child_sg_name)

    def attempt_ig_cleanup(self, connector, protocol, serial_number, force):
        """Attempt to cleanup an orphan initiator group

        :param connector: connector object
        :param protocol: iscsi or fc
        :param serial_number: extra the array serial number
        :param force: flag to indicate if operation should be forced
        """
        protocol = self.utils.get_short_protocol_type(protocol)
        host_name = connector['host']
        short_host_name = self.utils.get_host_short_name(host_name)
        init_group = (
            ("OS-%(shortHostName)s-%(protocol)s-IG"
             % {'shortHostName': short_host_name,
                'protocol': protocol}))
        self._check_ig_rollback(
            serial_number, init_group, connector, force)
