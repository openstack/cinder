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

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.dell_emc.vmax import utils

LOG = logging.getLogger(__name__)


class VMAXProvision(object):
    """Provisioning Class for Dell EMC VMAX volume drivers.

    It supports VMAX arrays.
    """
    def __init__(self, rest):
        self.utils = utils.VMAXUtils()
        self.rest = rest

    def create_storage_group(
            self, array, storagegroup_name, srp, slo, workload, extra_specs):
        """Create a new storage group.

        :param array: the array serial number
        :param storagegroup_name: the group name (String)
        :param srp: the SRP (String)
        :param slo: the SLO (String)
        :param workload: the workload (String)
        :param extra_specs: additional info
        :returns: storagegroup - storage group object
        """
        start_time = time.time()

        @coordination.synchronized("emc-sg-{storage_group}")
        def do_create_storage_group(storage_group):
            storagegroup = self.rest.create_storage_group(
                array, storage_group, srp, slo, workload, extra_specs)

            LOG.debug("Create storage group took: %(delta)s H:MM:SS.",
                      {'delta': self.utils.get_time_delta(start_time,
                                                          time.time())})
            LOG.info("Storage group %(sg)s created successfully.",
                     {'sg': storagegroup_name})
            return storagegroup

        return do_create_storage_group(storagegroup_name)

    def create_volume_from_sg(self, array, volume_name, storagegroup_name,
                              volume_size, extra_specs):
        """Create a new volume in the given storage group.

        :param array: the array serial number
        :param volume_name: the volume name (String)
        :param storagegroup_name: the storage group name
        :param volume_size: volume size (String)
        :param extra_specs: the extra specifications
        :returns: dict -- volume_dict - the volume dict
        """
        @coordination.synchronized("emc-sg-{storage_group}")
        def do_create_volume_from_sg(storage_group):
            start_time = time.time()

            volume_dict = self.rest.create_volume_from_sg(
                array, volume_name, storage_group,
                volume_size, extra_specs)

            LOG.debug("Create volume from storage group "
                      "took: %(delta)s H:MM:SS.",
                      {'delta': self.utils.get_time_delta(start_time,
                                                          time.time())})
            return volume_dict
        return do_create_volume_from_sg(storagegroup_name)

    def delete_volume_from_srp(self, array, device_id, volume_name):
        """Delete a volume from the srp.

        :param array: the array serial number
        :param device_id:  the volume device id
        :param volume_name: the volume name
        """
        start_time = time.time()
        LOG.debug("Delete volume %(volume_name)s from srp.",
                  {'volume_name': volume_name})
        self.rest.delete_volume(array, device_id)
        LOG.debug("Delete volume took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(
                      start_time, time.time())})

    def create_volume_snapvx(self, array, source_device_id,
                             snap_name, extra_specs):
        """Create a snapVx of a volume.

        :param array: the array serial number
        :param source_device_id: source volume device id
        :param snap_name: the snapshot name
        :param extra_specs: the extra specifications
        """
        start_time = time.time()
        LOG.debug("Create Snap Vx snapshot of: %(source)s.",
                  {'source': source_device_id})
        self.rest.create_volume_snap(
            array, snap_name, source_device_id, extra_specs)
        LOG.debug("Create volume snapVx took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(start_time,
                                                      time.time())})

    def create_volume_replica(
            self, array, source_device_id, target_device_id,
            snap_name, extra_specs, create_snap=False):
        """Create a snap vx of a source and copy to a target.

        :param array: the array serial number
        :param source_device_id: source volume device id
        :param target_device_id: target volume device id
        :param snap_name: the name for the snap shot
        :param extra_specs: extra specifications
        :param create_snap: Flag for create snapvx
        """
        start_time = time.time()
        if create_snap:
            self.create_volume_snapvx(array, source_device_id,
                                      snap_name, extra_specs)
        # Link source to target
        self.rest.modify_volume_snap(
            array, source_device_id, target_device_id, snap_name,
            extra_specs, link=True)

        LOG.debug("Create element replica took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(start_time,
                                                      time.time())})

    def break_replication_relationship(
            self, array, target_device_id, source_device_id, snap_name,
            extra_specs, wait_for_sync=True):
        """Unlink a snapshot from its target volume.

        :param array: the array serial number
        :param source_device_id: source volume device id
        :param target_device_id: target volume device id
        :param snap_name: the name for the snap shot
        :param extra_specs: extra specifications
        :param wait_for_sync: flag for wait for sync
        """
        LOG.debug("Break snap vx link relationship between: %(src)s "
                  "and: %(tgt)s.",
                  {'src': source_device_id, 'tgt': target_device_id})

        if wait_for_sync:
            self.rest.is_sync_complete(array, source_device_id,
                                       target_device_id, snap_name,
                                       extra_specs)
        try:
            self.rest.modify_volume_snap(
                array, source_device_id, target_device_id, snap_name,
                extra_specs, unlink=True)
        except Exception as e:
            LOG.error(
                "Error modifying volume snap. Exception received: %(e)s.",
                {'e': e})

    def delete_volume_snap(self, array, snap_name, source_device_id):
        """Delete a snapVx snapshot of a volume.

        :param array: the array serial number
        :param snap_name: the snapshot name
        :param source_device_id: the source device id
        """
        LOG.debug("Delete SnapVx: %(snap_name)s for volume %(vol)s.",
                  {'vol': source_device_id, 'snap_name': snap_name})
        self.rest.delete_volume_snap(array, snap_name, source_device_id)

    def delete_temp_volume_snap(self, array, snap_name, source_device_id):
        """Delete the temporary snapshot created for clone operations.

        There can be instances where the source and target both attempt to
        delete a temp snapshot simultaneously, so we must lock the snap and
        then double check it is on the array.
        :param array: the array serial number
        :param snap_name: the snapshot name
        :param source_device_id: the source device id
        """

        @coordination.synchronized("emc-snapvx-{snapvx_name}")
        def do_delete_temp_snap(snapvx_name):
            # Ensure snap has not been recently deleted
            if self.rest.get_volume_snap(
                    array, source_device_id, snapvx_name):
                self.delete_volume_snap(array, snapvx_name, source_device_id)

        do_delete_temp_snap(snap_name)

    def delete_volume_snap_check_for_links(self, array, snap_name,
                                           source_device, extra_specs):
        """Check if a snap has any links before deletion.

        If a snapshot has any links, break the replication relationship
        before deletion.
        :param array: the array serial number
        :param snap_name: the snapshot name
        :param source_device: the source device id
        :param extra_specs: the extra specifications
        """
        LOG.debug("Check for linked devices to SnapVx: %(snap_name)s "
                  "for volume %(vol)s.",
                  {'vol': source_device, 'snap_name': snap_name})
        linked_list = self.rest.get_snap_linked_device_list(
            array, source_device, snap_name)
        for link in linked_list:
            target_device = link['targetDevice']
            self.break_replication_relationship(
                array, target_device, source_device, snap_name, extra_specs)
        self.delete_volume_snap(array, snap_name, source_device)

    def extend_volume(self, array, device_id, new_size, extra_specs):
        """Extend a volume.

        :param array: the array serial number
        :param device_id: the volume device id
        :param new_size: the new size (GB)
        :param extra_specs: the extra specifications
        :return: status_code
        """
        start_time = time.time()
        self.rest.extend_volume(array, device_id, new_size, extra_specs)
        LOG.debug("Extend VMAX volume took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(start_time,
                                                      time.time())})

    def get_srp_pool_stats(self, array, array_info):
        """Get the srp capacity stats.

        :param array: the array serial number
        :param array_info: the array dict
        :returns: total_capacity_gb
        :returns: remaining_capacity_gb
        :returns: subscribed_capacity_gb
        :returns: array_reserve_percent
        :returns: wlp_enabled
        """
        total_capacity_gb = 0
        remaining_capacity_gb = 0
        allocated_capacity_gb = None
        subscribed_capacity_gb = 0
        array_reserve_percent = 0
        wlp_enabled = False
        srp = array_info['srpName']
        LOG.debug(
            "Retrieving capacity for srp %(srpName)s on array %(array)s.",
            {'srpName': srp, 'array': array})

        srp_details = self.rest.get_srp_by_name(array, srp)
        if not srp_details:
            LOG.error("Unable to retrieve srp instance of %(srpName)s on "
                      "array %(array)s.",
                      {'srpName': srp, 'array': array})
            return 0, 0, 0, 0, False
        try:
            total_capacity_gb = srp_details['total_usable_cap_gb']
            allocated_capacity_gb = srp_details['total_allocated_cap_gb']
            subscribed_capacity_gb = srp_details['total_subscribed_cap_gb']
            remaining_capacity_gb = float(
                total_capacity_gb - allocated_capacity_gb)
            array_reserve_percent = srp_details['reserved_cap_percent']
        except KeyError:
            pass

        total_slo_capacity = (
            self._get_remaining_slo_capacity_wlp(
                array, srp, array_info))
        if total_slo_capacity != -1 and allocated_capacity_gb:
            remaining_capacity_gb = float(
                total_slo_capacity - allocated_capacity_gb)
            wlp_enabled = True
        else:
            LOG.debug(
                "Remaining capacity %(remaining_capacity_gb)s "
                "GBs is determined from SRP capacity "
                "and not the SLO capacity. Performance may "
                "not be what you expect.",
                {'remaining_capacity_gb': remaining_capacity_gb})

        return (total_capacity_gb, remaining_capacity_gb,
                subscribed_capacity_gb, array_reserve_percent, wlp_enabled)

    def _get_remaining_slo_capacity_wlp(self, array, srp, array_info):
        """Get the remaining capacity of the SLO/ workload combination.

        This is derived from the WLP portion of Unisphere. Please
        see the UniSphere doc and the readme doc for details.
        :param array: the array serial number
        :param srp: the srp name
        :param array_info: array info dict
        :return: remaining_capacity
        """
        remaining_capacity = -1
        if array_info['SLO']:
            headroom_capacity = self.rest.get_headroom_capacity(
                array, srp, array_info['SLO'], array_info['Workload'])
            if headroom_capacity:
                remaining_capacity = headroom_capacity
                LOG.debug("Received remaining SLO Capacity %(remaining)s GBs "
                          "for SLO %(SLO)s and workload %(workload)s.",
                          {'remaining': remaining_capacity,
                           'SLO': array_info['SLO'],
                           'workload': array_info['Workload']})
        return remaining_capacity

    def verify_slo_workload(self, array, slo, workload, srp):
        """Check if SLO and workload values are valid.

        :param array: the array serial number
        :param slo: Service Level Object e.g bronze
        :param workload: workload e.g DSS
        :param srp: the storage resource pool name
        :returns: boolean
        """
        is_valid_slo, is_valid_workload = False, False

        if workload:
            if workload.lower() == 'none':
                workload = None

        if not workload:
            is_valid_workload = True

        valid_slos = self.rest.get_slo_list(array)
        valid_workloads = self.rest.get_workload_settings(array)
        for valid_slo in valid_slos:
            if slo == valid_slo:
                is_valid_slo = True
                break

        for valid_workload in valid_workloads:
            if workload == valid_workload:
                is_valid_workload = True
                break

        if not slo:
            is_valid_slo = True
            if workload:
                is_valid_workload = False

        if not is_valid_slo:
            LOG.error(
                "SLO: %(slo)s is not valid. Valid values are: "
                "%(valid_slos)s.", {'slo': slo, 'valid_slos': valid_slos})

        if not is_valid_workload:
            LOG.error(
                "Workload: %(workload)s is not valid. Valid values are "
                "%(valid_workloads)s. Note you cannot "
                "set a workload without an SLO.",
                {'workload': workload, 'valid_workloads': valid_workloads})

        return is_valid_slo, is_valid_workload

    def get_slo_workload_settings_from_storage_group(
            self, array, sg_name):
        """Get slo and workload settings from a storage group.

        :param array: the array serial number
        :param sg_name: the storage group name
        :return: storage group slo settings
        """
        slo = 'NONE'
        workload = 'NONE'
        storage_group = self.rest.get_storage_group(array, sg_name)
        if storage_group:
            try:
                slo = storage_group['slo']
                workload = storage_group['workload']
            except KeyError:
                pass
        else:
            exception_message = (_(
                "Could not retrieve storage group %(sg_name)%. ") %
                {'sg_name': sg_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(data=exception_message)
        return '%(slo)s+%(workload)s' % {'slo': slo, 'workload': workload}
