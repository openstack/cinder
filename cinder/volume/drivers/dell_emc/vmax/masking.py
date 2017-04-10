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

import time

from oslo_log import log as logging
import six

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.dell_emc.vmax import provision
from cinder.volume.drivers.dell_emc.vmax import utils

LOG = logging.getLogger(__name__)


class VMAXMasking(object):
    """Masking class for Dell EMC VMAX.

    Masking code to dynamically create a masking view.
    It supports VMAX arrays.
    """
    def __init__(self, prtcl, rest):
        self.protocol = prtcl
        self.utils = utils.VMAXUtils()
        self.rest = rest
        self.provision = provision.VMAXProvision(self.rest)

    def setup_masking_view(
            self, serial_number, masking_view_dict, extra_specs):

        @coordination.synchronized("emc-mv-{maskingview_name}")
        def do_get_or_create_masking_view_and_map_lun(maskingview_name):
            return self.get_or_create_masking_view_and_map_lun(
                serial_number, maskingview_name, masking_view_dict,
                extra_specs)
        return do_get_or_create_masking_view_and_map_lun(
            masking_view_dict[utils.MV_NAME])

    def get_or_create_masking_view_and_map_lun(
            self, serial_number, maskingview_name, masking_view_dict,
            extra_specs):
        """Get or Create a masking view and add a volume to the storage group.

        Given a masking view dict either get or create a masking view and add
        the volume to the associated storage group.
        :param serial_number: the array serial number
        :param maskingview_name: the masking view name
        :param masking_view_dict: the masking view dict
        :param extra_specs: the extra specifications
        :return: rollback_dict
        :raises: VolumeBackendAPIException
        """
        storagegroup_name = masking_view_dict[utils.SG_NAME]
        volume_name = masking_view_dict[utils.VOL_NAME]
        masking_view_dict[utils.EXTRA_SPECS] = extra_specs
        device_id = masking_view_dict[utils.DEVICE_ID]
        default_sg_name = self._get_default_storagegroup_and_remove_vol(
            serial_number, device_id, masking_view_dict, volume_name,
            extra_specs)

        try:
            error_message = self._get_or_create_masking_view(
                serial_number, masking_view_dict, extra_specs)
            LOG.debug(
                "The masking view in the attach operation is "
                "%(masking_name)s. The storage group "
                "in the masking view is %(storage_name)s.",
                {'masking_name': maskingview_name,
                 'storage_name': storagegroup_name})
        except Exception as e:
            LOG.exception(
                "Masking View creation or retrieval was not successful "
                "for masking view %(maskingview_name)s. "
                "Attempting rollback.",
                {'maskingview_name': masking_view_dict[utils.MV_NAME]})
            error_message = six.text_type(e)

        rollback_dict = masking_view_dict
        try:
            rollback_dict['portgroup_name'] = (
                self.rest.get_element_from_masking_view(
                    serial_number, maskingview_name, portgroup=True))
        except Exception as e:
            error_message = ("Error retrieving port group. Exception "
                             "received: %(e)s" % {'e': six.text_type(e)})
        rollback_dict['default_sg_name'] = default_sg_name

        if error_message:
            # Rollback code if we cannot complete any of the steps above
            # successfully then we must roll back by adding the volume back to
            # the default storage group for that slo/workload combination.

            if rollback_dict['slo'] is not None:
                self.check_if_rollback_action_for_masking_required(
                    serial_number, device_id, masking_view_dict)

            else:
                self._check_adding_volume_to_storage_group(
                    serial_number, device_id, rollback_dict['default_sg_name'],
                    masking_view_dict[utils.VOL_NAME],
                    masking_view_dict[utils.EXTRA_SPECS])

            exception_message = (_(
                "Failed to get, create or add volume %(volumeName)s "
                "to masking view %(maskingview_name)s. "
                "The error message received was %(errorMessage)s.")
                % {'maskingview_name': maskingview_name,
                   'volumeName': volume_name,
                   'errorMessage': error_message})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)

        return rollback_dict

    def _get_default_storagegroup_and_remove_vol(
            self, serial_number, device_id, masking_view_dict,
            volume_name, extra_specs):
        """Get the default storage group and remove volume.

        :param serial_number: the array serial number
        :param device_id: the device id
        :param masking_view_dict: the masking view dict
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        :return: default_sg_name
        """
        default_sg_name = self.utils.get_default_storage_group_name(
            masking_view_dict[utils.SRP],
            masking_view_dict[utils.SLO],
            masking_view_dict[utils.WORKLOAD])

        check_vol = self.rest.is_volume_in_storagegroup(
            serial_number, device_id, default_sg_name)
        if check_vol:
            self.remove_volume_from_sg(
                serial_number, device_id, volume_name, default_sg_name,
                extra_specs)
        else:
            LOG.warning(
                "Volume: %(volume_name)s does not belong "
                "to default storage group %(default_sg_name)s.",
                {'volume_name': volume_name,
                 'default_sg_name': default_sg_name})
        return default_sg_name

    def _get_or_create_masking_view(self, serial_number, masking_view_dict,
                                    extra_specs):
        """Retrieve an existing masking view or create a new one.

        :param serial_number: the array serial number
        :param masking_view_dict: the masking view dict
        :param extra_specs: the extra specifications
        :return: error message
        """
        maskingview_name = masking_view_dict[utils.MV_NAME]

        masking_view_details = self.rest.get_masking_view(
            serial_number, masking_view_name=maskingview_name)
        if not masking_view_details:
            error_message = self._create_new_masking_view(
                serial_number, masking_view_dict, maskingview_name,
                extra_specs)

        else:
            storagegroup_name, error_message = (
                self._validate_existing_masking_view(
                    serial_number, masking_view_dict, maskingview_name,
                    extra_specs))

        return error_message

    def _create_new_masking_view(self, serial_number, masking_view_dict,
                                 maskingview_name, extra_specs):
        """Create a new masking view.

        :param serial_number: the array serial number
        :param masking_view_dict: the masking view dict
        :param maskingview_name: the masking view name
        :param extra_specs: the extra specifications
        :return: error_message
        """
        init_group_name = masking_view_dict[utils.IG_NAME]
        parent_sg_name = masking_view_dict[utils.PARENT_SG_NAME]
        storagegroup_name = masking_view_dict[utils.SG_NAME]
        connector = masking_view_dict[utils.CONNECTOR]
        port_group_name = masking_view_dict[utils.PORTGROUPNAME]
        LOG.info("Port Group in masking view operation: %(port_group_name)s.",
                 {'port_group_name': port_group_name})

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

        __, error_message = self._check_port_group(
            serial_number, port_group_name)
        if error_message:
            return error_message

        init_group_name, error_message = (self._get_or_create_initiator_group(
            serial_number, init_group_name, connector, extra_specs))
        if error_message:
            return error_message

        # Only after the components of the MV have been validated,
        # add the volume to the storage group and recheck that it
        # has been successfully added.  This is necessary before
        # creating a new masking view.
        error_message = self._check_adding_volume_to_storage_group(
            serial_number, masking_view_dict[utils.DEVICE_ID],
            storagegroup_name, masking_view_dict[utils.VOL_NAME],
            masking_view_dict[utils.EXTRA_SPECS])
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

    def _validate_existing_masking_view(self, serial_number, masking_view_dict,
                                        maskingview_name, extra_specs):
        """Validate the components of an existing masking view.

        :param serial_number: the array serial number
        :param masking_view_dict: the masking view dict
        :param maskingview_name: the amsking view name
        :param extra_specs: the extra specifications
        :return: storage_group_name -- string, msg -- string
        """
        storage_group_name, msg = self._check_existing_storage_group(
            serial_number, maskingview_name, masking_view_dict)
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
        :return: error_message or None
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
        :return: msg -- string or None
        """
        msg = None
        srp = extra_specs[utils.SRP]
        workload = extra_specs[utils.WORKLOAD]
        if parent:
            slo = None
        else:
            slo = extra_specs[utils.SLO]
        storagegroup = self.rest.get_storage_group(
            serial_number, storagegroup_name)
        if storagegroup is None:
            storagegroup = self.provision.create_storage_group(
                serial_number, storagegroup_name, srp, slo, workload,
                extra_specs)

        if storagegroup is None:
            msg = ("Cannot get or create a storage group: "
                   "%(storagegroup_name)s for volume %(volume_name)s."
                   % {'storagegroup_name': storagegroup_name,
                      'volume_name': masking_view_dict[utils.VOL_NAME]})
            LOG.error(msg)
        return msg

    def _check_existing_storage_group(
            self, serial_number, maskingview_name, masking_view_dict):
        """Check if the masking view has the child storage group.

        Get the parent storage group associated with a masking view and check
        if the required child storage group is already a member. If not, get
        or create the child storage group.
        :param serial_number: the array serial number
        :param maskingview_name: the masking view name
        :param masking_view_dict: the masking view dict
        :return: storage group name, msg
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
                msg = self._check_adding_volume_to_storage_group(
                    serial_number, masking_view_dict[utils.DEVICE_ID],
                    child_sg_name, masking_view_dict[utils.VOL_NAME],
                    masking_view_dict[utils.EXTRA_SPECS])
            if not msg and not check_child:
                msg = self._check_add_child_sg_to_parent_sg(
                    serial_number, child_sg_name, sg_from_mv,
                    masking_view_dict[utils.EXTRA_SPECS])

        return child_sg_name, msg

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
        :return: name of the initiator group -- string, msg
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
        :return: msg
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

    def _remove_vol_from_storage_group(
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
                data=exception_message)

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
                raise exception.VolumeBackendAPIException(data=msg)

        if not foundinitiatornames:
            msg = (_("Error finding %(name)s.") % {'name': name})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

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
        init_list = self.rest.get_in_use_initiator_list_from_array(
            serial_number)
        for initiator in initiator_names:
            found_init = [init for init in init_list if initiator in init]
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
        :return: error_message -- string or None
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
            self, serial_number, device_id, rollback_dict):
        """Rollback action for volumes with an associated service level.

        We need to be able to return the volume to the default storage group
        if anything has gone wrong. The volume can also potentially belong to
        a storage group that is not the default depending on where
        the exception occurred. We also may need to clean up any unused
        initiator groups.
        :param serial_number: the array serial number
        :param device_id: the device id
        :param rollback_dict: the rollback dict
        :return: error message -- string, or None
        :raises: VolumeBackendAPIException
        """
        message = None
        # Check if ig has been created. If so, check for other
        # masking views associated with the ig. If none, delete the ig.
        self._check_ig_rollback(
            serial_number, rollback_dict['init_group_name'],
            rollback_dict['connector'])
        try:
            found_sg_name = (
                self.rest.get_storage_groups_from_volume(
                    serial_number, rollback_dict['device_id']))
            # Volume is not associated with any storage group so add
            # it back to the default.
            if not found_sg_name:
                error_message = self._check_adding_volume_to_storage_group(
                    serial_number, device_id,
                    rollback_dict['default_sg_name'],
                    rollback_dict[utils.VOL_NAME],
                    rollback_dict[utils.EXTRA_SPECS])
                if error_message:
                    LOG.error(error_message)
                message = (_("Rollback"))
            else:
                LOG.info("The storage group found is %(found_sg_name)s.",
                         {'found_sg_name': found_sg_name})

                # Check the name, see if it is the default storage group
                # or another.
                if found_sg_name != rollback_dict['default_sg_name']:
                    # Remove it from its current storage group and return it
                    # to its default masking view if slo is defined.
                    self.remove_and_reset_members(
                        serial_number, device_id,
                        rollback_dict['volume_name'],
                        rollback_dict['extra_specs'])
                    message = (_("Rollback - Volume in another storage "
                                 "group besides default storage group."))
        except Exception as e:
            error_message = (_(
                "Rollback for Volume: %(volume_name)s has failed. "
                "Please contact your system administrator to manually return "
                "your volume to the default storage group for its slo. "
                "Exception received: %(e)s")
                % {'volume_name': rollback_dict['volume_name'],
                   'e': six.text_type(e)})
            LOG.exception(error_message)
            raise exception.VolumeBackendAPIException(data=error_message)
        return message

    def _verify_initiator_group_from_masking_view(
            self, serial_number, maskingview_name, maskingview_dict,
            ig_from_mv, storagegroup_name, portgroup_name, extra_specs):
        """Check that the initiator group contains the correct initiators.

        If using an existing masking view check that the initiator group
        contains the correct initiators.  If it does not contain the correct
        initiators then we delete the initiator group from the masking view,
        re-create it with the correct initiators and add it to the masking view
        NOTE:  VMAX does not support ModifyMaskingView so we must first
               delete the masking view and recreate it.
        :param serial_number: the array serial number
        :param maskingview_name: name of the masking view
        :param maskingview_dict: the masking view dict
        :param ig_from_mv: the initiator group name
        :param storagegroup_name: the storage group
        :param portgroup_name: the port group
        :param extra_specs: extra specifications
        :return: bool, found_ig_from_connector
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
        :return: the initiator group name
        """
        self.rest.create_initiator_group(
            serial_number, init_group_name, initiator_names, extra_specs)
        return init_group_name

    def _check_ig_rollback(
            self, serial_number, init_group_name, connector):
        """Check if rollback action is required on an initiator group.

        If anything goes wrong on a masking view creation, we need to check if
        the process created a now-stale initiator group before failing, i.e.
        an initiator group a) matching the name used in the mv process and
        b) not associated with any other masking views.
        If a stale ig exists, delete the ig.
        :param serial_number: the array serial number
        :param init_group_name: the initiator group name
        :param connector: the connector object
        """
        initiator_names = self.find_initiator_names(connector)
        found_ig_name = self._find_initiator_group(
            serial_number, initiator_names)
        if found_ig_name:
            if found_ig_name == init_group_name:
                host = init_group_name.split("-")[1]
                LOG.debug("Searching for masking views associated with "
                          "%(init_group_name)s",
                          {'init_group_name': init_group_name})
                self._last_volume_delete_initiator_group(
                    serial_number, found_ig_name, host)

    def remove_and_reset_members(
            self, serial_number, device_id, volume_name, extra_specs,
            reset=True):
        """This is called on a delete, unmap device or rollback.

        :param serial_number: the array serial number
        :param device_id: the volume device id
        :param volume_name: the volume name
        :param extra_specs: additional info
        :param reset: reset, return to original SG (optional)
        """
        self._cleanup_deletion(
            serial_number, device_id, volume_name, extra_specs)
        if reset:
            self.return_volume_to_default_storage_group(
                serial_number, device_id, volume_name, extra_specs)

    def _cleanup_deletion(
            self, serial_number, device_id, volume_name, extra_specs):
        """Prepare a volume for a delete operation.

        :param serial_number: the array serial number
        :param device_id: the volume device id
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        """
        storagegroup_names = (self.rest.get_storage_groups_from_volume(
            serial_number, device_id))
        if storagegroup_names:
            for sg_name in storagegroup_names:
                self.remove_volume_from_sg(
                    serial_number, device_id, volume_name, sg_name,
                    extra_specs)

    def remove_volume_from_sg(
            self, serial_number, device_id, vol_name, storagegroup_name,
            extra_specs):
        """Remove a volume from a storage group.

        :param serial_number: the array serial number
        :param device_id: the volume device id
        :param vol_name: the volume name
        :param storagegroup_name: the storage group name
        :param extra_specs: the extra specifications
        """
        masking_list = self.rest.get_masking_views_from_storage_group(
            serial_number, storagegroup_name)
        if not masking_list:
            LOG.debug("No masking views associated with storage group "
                      "%(sg_name)s" % {'sg_name': storagegroup_name})

            @coordination.synchronized("emc-sg-{sg_name}")
            def do_remove_volume_from_sg(sg_name):
                # Make sure volume hasn't been recently removed from the sg
                is_vol = self.rest.is_volume_in_storagegroup(
                    serial_number, device_id, sg_name)
                if is_vol:
                    num_vol_in_sg = self.rest.get_num_vols_in_sg(
                        serial_number, sg_name)
                    LOG.debug(
                        "There are %(num_vol)d volumes in the storage group "
                        "%(sg_name)s.",
                        {'num_vol': num_vol_in_sg,
                         'sg_name': sg_name})

                    if num_vol_in_sg == 1:
                        # Last volume in the storage group - delete sg.
                        self._last_vol_in_sg(
                            serial_number, device_id, vol_name, sg_name,
                            extra_specs)
                    else:
                        # Not the last volume so remove it from storage group
                        self._multiple_vols_in_sg(
                            serial_number, device_id, sg_name, vol_name,
                            extra_specs)
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
                            extra_specs)
                    else:
                        # Not the last volume so remove it from storage group
                        self._multiple_vols_in_sg(
                            serial_number, device_id, sg_name, vol_name,
                            extra_specs)
                else:
                    LOG.info("Volume with device_id %(dev)s is no longer a "
                             "member of %(sg)s",
                             {'dev': device_id, 'sg': sg_name})

            return do_remove_volume_from_sg(masking_name, storagegroup_name,
                                            parent_sg_name)

    def _last_vol_in_sg(self, serial_number, device_id, volume_name,
                        storagegroup_name, extra_specs):
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
        :return: status -- bool
        """
        LOG.debug("Only one volume remains in storage group "
                  "%(sgname)s. Driver will attempt cleanup.",
                  {'sgname': storagegroup_name})
        maskingview_list = self.rest.get_masking_views_from_storage_group(
            serial_number, storagegroup_name)
        if not bool(maskingview_list):
            status = self._last_vol_no_masking_views(
                serial_number, storagegroup_name, device_id, volume_name,
                extra_specs)
        else:
            status = self._last_vol_masking_views(
                serial_number, storagegroup_name, maskingview_list,
                device_id, volume_name, extra_specs)
        return status

    def _last_vol_no_masking_views(self, serial_number, storagegroup_name,
                                   device_id, volume_name, extra_specs):
        """Remove the last vol from an sg not associated with an mv.

        Helper function for removing the last vol from a storage group
        which is not associated with a masking view.
        :param serial_number: the array serial number
        :param storagegroup_name: the storage group name
        :param device_id: the device id
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        :return: status -- bool
        """
        # Check if storage group is a child sg:
        parent_sg = self.get_parent_sg_from_child(
            serial_number, storagegroup_name)
        # Delete the storage group.
        if parent_sg is None:
            self.rest.delete_storage_group(serial_number, storagegroup_name)
            status = True
        else:
            num_vols_parent = self.rest.get_num_vols_in_sg(
                serial_number, parent_sg)
            if num_vols_parent == 1:
                self._delete_cascaded_storage_groups(
                    serial_number, storagegroup_name, parent_sg)
            else:
                self._remove_last_vol_and_delete_sg(
                    serial_number, device_id, volume_name,
                    storagegroup_name, extra_specs, parent_sg)
            status = True
        return status

    def _last_vol_masking_views(
            self, serial_number, storagegroup_name, maskingview_list,
            device_id, volume_name, extra_specs):
        """Remove the last vol from an sg associated with masking views.

        Helper function for removing the last vol from a storage group
        which is associated with one or more masking views.
        :param serial_number: the array serial number
        :param storagegroup_name: the storage group name
        :param maskingview_list: the liast of masking views
        :param device_id: the device id
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        :return: status -- bool
        """
        status = False
        for mv in maskingview_list:
            num_vols_in_mv, parent_sg_name = (
                self._get_num_vols_from_mv(serial_number, mv))
            # If the volume is the last in the masking view, full cleanup
            if num_vols_in_mv == 1:
                def do_delete_mv_ig_and_sg():
                    return self._delete_mv_ig_and_sg(
                        serial_number, mv, storagegroup_name, parent_sg_name)

                do_delete_mv_ig_and_sg()
            else:
                self._remove_last_vol_and_delete_sg(
                    serial_number, device_id, volume_name,
                    storagegroup_name, extra_specs, parent_sg_name)
            status = True
        return status

    def get_parent_sg_from_child(self, serial_number, storagegroup_name):
        """Given a storage group name, get its parent storage group, if any.

        :param serial_number: the array serial number
        :param storagegroup_name: the name of the storage group
        :return: the parent storage group name, or None
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
        :return: num_vols, parent_sg_name
        """
        parent_sg_name = self.rest.get_element_from_masking_view(
            serial_number, maskingview_name, storagegroup=True)
        num_vols = self.rest.get_num_vols_in_sg(serial_number, parent_sg_name)
        return num_vols, parent_sg_name

    def _multiple_vols_in_sg(self, serial_number, device_id, storagegroup_name,
                             volume_name, extra_specs):
        """Remove the volume from the SG.

        If the volume is not the last in the storage group,
        remove the volume from the SG and leave the sg on the array.
        :param serial_number: array serial number
        :param device_id: volume device id
        :param volume_name: volume name
        :param storagegroup_name: storage group name
        :param extra_specs: extra specifications
        """
        self._remove_vol_from_storage_group(
            serial_number, device_id, storagegroup_name,
            volume_name, extra_specs)

        LOG.debug(
            "RemoveMembers for volume %(volume_name)s completed "
            "successfully.", {'volume_name': volume_name})

        num_vol_in_sg = self.rest.get_num_vols_in_sg(
            serial_number, storagegroup_name)
        LOG.debug("There are %(num_vol)d volumes remaining in the storage "
                  "group %(sg_name)s." %
                  {'num_vol': num_vol_in_sg,
                   'sg_name': storagegroup_name})

    def _delete_cascaded_storage_groups(self, serial_number, child_sg_name,
                                        parent_sg_name):
        """Delete a child and parent storage groups.

        :param serial_number: the array serial number
        :param child_sg_name: the child storage group name
        :param parent_sg_name: the parent storage group name
        """
        self.rest.delete_storage_group(serial_number, parent_sg_name)
        self.rest.delete_storage_group(serial_number, child_sg_name)

        LOG.debug("Storage Groups %(storagegroup_name)s and %(parent)s "
                  "successfully deleted.",
                  {'storagegroup_name': child_sg_name,
                   'parent': parent_sg_name})

    def _delete_mv_ig_and_sg(
            self, serial_number, masking_view, storagegroup_name,
            parent_sg_name):
        """Delete the masking view, storage groups and initiator group.

        :param serial_number: array serial number
        :param masking_view: masking view name
        :param storagegroup_name: storage group name
        :param parent_sg_name: the parent storage group name
        """
        host = masking_view.split("-")[1]

        initiatorgroup = self.rest.get_element_from_masking_view(
            serial_number, masking_view, host=True)
        self._last_volume_delete_masking_view(serial_number, masking_view)
        self._last_volume_delete_initiator_group(
            serial_number, initiatorgroup, host)
        self._delete_cascaded_storage_groups(serial_number, storagegroup_name,
                                             parent_sg_name)

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

    def return_volume_to_default_storage_group(
            self, serial_number, device_id, volume_name, extra_specs):
        """Return volume to its default storage group.

        :param serial_number: the array serial number
        :param device_id: the volume device id
        :param volume_name: the volume name
        :param extra_specs: the extra specifications
        """
        storagegroup_name = self.get_or_create_default_storage_group(
            serial_number, extra_specs[utils.SRP], extra_specs[utils.SLO],
            extra_specs[utils.WORKLOAD], extra_specs)

        self._check_adding_volume_to_storage_group(
            serial_number, device_id, storagegroup_name, volume_name,
            extra_specs)

    def get_or_create_default_storage_group(
            self, serial_number, srp, slo, workload, extra_specs):
        """Get or create a default storage group.

        :param serial_number: the array serial number
        :param srp: the SRP name
        :param slo: the SLO
        :param workload: the workload
        :param extra_specs: extra specifications
        :returns: storagegroup_name
        :raises: VolumeBackendAPIException
        """
        storagegroup, storagegroup_name = (
            self.rest.get_vmax_default_storage_group(
                serial_number, srp, slo, workload))
        if storagegroup is None:
            self.provision.create_storage_group(
                serial_number, storagegroup_name, srp, slo, workload,
                extra_specs)
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
                    data=exception_message)

        return storagegroup_name

    def _remove_last_vol_and_delete_sg(
            self, serial_number, device_id, volume_name,
            storagegroup_name, extra_specs, parent_sg_name=None):
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
        self._remove_vol_from_storage_group(
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

        Delete the Initiator group if it has been created by the VMAX driver,
        and if there are no masking views associated with it.
        :param serial_number: the array serial number
        :param initiatorgroup_name: initiator group name
        :param host: the short name of the host
        """
        protocol = self.utils.get_short_protocol_type(self.protocol)
        default_ig_name = ("OS-%(shortHostName)s-%(protocol)s-IG"
                           % {'shortHostName': host,
                              'protocol': protocol})

        if initiatorgroup_name == default_ig_name:
            maskingview_names = (
                self.rest.get_masking_views_by_initiator_group(
                    serial_number, initiatorgroup_name))
            if not maskingview_names:
                LOG.debug(
                    "Last volume associated with the initiator group - "
                    "deleting the associated initiator group "
                    "%(initiatorgroup_name)s.",
                    {'initiatorgroup_name': initiatorgroup_name})
                self.rest.delete_initiator_group(
                    serial_number, initiatorgroup_name)
            else:
                LOG.warning("Initiator group %(ig_name)s is associated with "
                            "masking views and can't be deleted. Number of "
                            "associated masking view is: %(nmv)d.",
                            {'ig_name': initiatorgroup_name,
                             'nmv': len(maskingview_names)})
        else:
            LOG.warning("Initiator group %(ig_name)s was "
                        "not created by the VMAX driver so will "
                        "not be deleted by the VMAX driver.",
                        {'ig_name': initiatorgroup_name})
