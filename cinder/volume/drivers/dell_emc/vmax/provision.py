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
from oslo_service import loopingcall

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.dell_emc.vmax import utils

LOG = logging.getLogger(__name__)

WRITE_DISABLED = "Write Disabled"
UNLINK_INTERVAL = 15
UNLINK_RETRIES = 30


class VMAXProvision(object):
    """Provisioning Class for Dell EMC VMAX volume drivers.

    It supports VMAX arrays.
    """
    def __init__(self, rest):
        self.utils = utils.VMAXUtils()
        self.rest = rest

    def create_storage_group(
            self, array, storagegroup_name, srp, slo, workload,
            extra_specs, do_disable_compression=False):
        """Create a new storage group.

        :param array: the array serial number
        :param storagegroup_name: the group name (String)
        :param srp: the SRP (String)
        :param slo: the SLO (String)
        :param workload: the workload (String)
        :param extra_specs: additional info
        :param do_disable_compression: disable compression flag
        :returns: storagegroup - storage group object
        """
        start_time = time.time()

        @coordination.synchronized("emc-sg-{storage_group}")
        def do_create_storage_group(storage_group):
            storagegroup = self.rest.create_storage_group(
                array, storage_group, srp, slo, workload, extra_specs,
                do_disable_compression)

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
            extra_specs):
        """Unlink a snapshot from its target volume.

        :param array: the array serial number
        :param source_device_id: source volume device id
        :param target_device_id: target volume device id
        :param snap_name: the name for the snap shot
        :param extra_specs: extra specifications
        """
        LOG.debug("Break snap vx link relationship between: %(src)s "
                  "and: %(tgt)s.",
                  {'src': source_device_id, 'tgt': target_device_id})

        self._unlink_volume(array, source_device_id, target_device_id,
                            snap_name, extra_specs)

    def _unlink_volume(
            self, array, source_device_id, target_device_id, snap_name,
            extra_specs):
        """Unlink a target volume from its source volume.

        :param array: the array serial number
        :param source_device_id: the source device id
        :param target_device_id: the target device id
        :param snap_name: the snap name
        :param extra_specs: extra specifications
        :return: return code
        """

        def _unlink_vol():
            """Called at an interval until the synchronization is finished.

            :raises: loopingcall.LoopingCallDone
            """
            retries = kwargs['retries']
            try:
                kwargs['retries'] = retries + 1
                if not kwargs['modify_vol_success']:
                    self.rest.modify_volume_snap(
                        array, source_device_id, target_device_id, snap_name,
                        extra_specs, unlink=True)
                    kwargs['modify_vol_success'] = True
            except exception.VolumeBackendAPIException:
                pass

            if kwargs['retries'] > UNLINK_RETRIES:
                LOG.error("_unlink_volume failed after %(retries)d "
                          "tries.", {'retries': retries})
                raise loopingcall.LoopingCallDone(retvalue=30)
            if kwargs['modify_vol_success']:
                raise loopingcall.LoopingCallDone()

        kwargs = {'retries': 0,
                  'modify_vol_success': False}
        timer = loopingcall.FixedIntervalLoopingCall(_unlink_vol)
        rc = timer.start(interval=UNLINK_INTERVAL).wait()
        return rc

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
        :returns: status_code
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
        """
        total_capacity_gb = 0
        remaining_capacity_gb = 0
        allocated_capacity_gb = None
        subscribed_capacity_gb = 0
        array_reserve_percent = 0
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

        LOG.debug(
            "Remaining capacity %(remaining_capacity_gb)s "
            "GBs is determined from SRP capacity ",
            {'remaining_capacity_gb': remaining_capacity_gb})

        return (total_capacity_gb, remaining_capacity_gb,
                subscribed_capacity_gb, array_reserve_percent)

    def verify_slo_workload(self, array, slo, workload, srp):
        """Check if SLO and workload values are valid.

        :param array: the array serial number
        :param slo: Service Level Object e.g bronze
        :param workload: workload e.g DSS
        :param srp: the storage resource pool name
        :returns: boolean
        """
        is_valid_slo, is_valid_workload = False, False

        if workload and workload.lower() == 'none':
            workload = None

        if not workload:
            is_valid_workload = True

        if slo and slo.lower() == 'none':
            slo = None

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
        :returns: storage group slo settings
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

    def break_rdf_relationship(self, array, device_id, target_device,
                               rdf_group, rep_extra_specs, state):
        """Break the rdf relationship between a pair of devices.

        :param array: the array serial number
        :param device_id: the source device id
        :param target_device: target device id
        :param rdf_group: the rdf group number
        :param rep_extra_specs: replication extra specs
        :param state: the state of the rdf pair
        """
        LOG.info("Splitting rdf pair: source device: %(src)s "
                 "target device: %(tgt)s.",
                 {'src': device_id, 'tgt': target_device})
        if state == 'Synchronized':
            self.rest.modify_rdf_device_pair(
                array, device_id, rdf_group, rep_extra_specs, split=True)
        LOG.info("Deleting rdf pair: source device: %(src)s "
                 "target device: %(tgt)s.",
                 {'src': device_id, 'tgt': target_device})
        self.rest.delete_rdf_pair(array, device_id, rdf_group)

    def failover_volume(self, array, device_id, rdf_group,
                        extra_specs, local_vol_state, failover):
        """Failover or back a volume pair.

        :param array: the array serial number
        :param device_id: the source device id
        :param rdf_group: the rdf group number
        :param extra_specs: extra specs
        :param local_vol_state: the local volume state
        :param failover: flag to indicate failover or failback -- bool
        """
        if local_vol_state == WRITE_DISABLED:
            LOG.info("Volume %(dev)s is already failed over.",
                     {'dev': device_id})
            return
        if failover:
            action = "Failing over"
        else:
            action = "Failing back"
        LOG.info("%(action)s rdf pair: source device: %(src)s ",
                 {'action': action, 'src': device_id})
        self.rest.modify_rdf_device_pair(
            array, device_id, rdf_group, extra_specs, split=False)

    def get_or_create_volume_group(self, array, group, extra_specs):
        """Get or create a volume group.

        Sometimes it may be necessary to recreate a volume group on the
        backend - for example, when the last member volume has been removed
        from the group, but the cinder group object has not been deleted.
        :param array: the array serial number
        :param group: the group object
        :param extra_specs: the extra specifications
        :return: group name
        """
        vol_grp_name = self.utils.update_volume_group_name(group)
        return self.get_or_create_group(array, vol_grp_name, extra_specs)

    def get_or_create_group(self, array, group_name, extra_specs):
        """Get or create a generic volume group.

        :param array: the array serial number
        :param group_name: the group name
        :param extra_specs: the extra specifications
        :return: group name
        """
        storage_group = self.rest.get_storage_group(array, group_name)
        if not storage_group:
            self.create_volume_group(array, group_name, extra_specs)
        return group_name

    def create_volume_group(self, array, group_name, extra_specs):
        """Create a generic volume group.

        :param array: the array serial number
        :param group_name: the name of the group
        :param extra_specs: the extra specifications
        :returns: volume_group
        """
        return self.create_storage_group(array, group_name,
                                         None, None, None, extra_specs)

    def create_group_replica(
            self, array, source_group, snap_name, extra_specs):
        """Create a replica (snapVx) of a volume group.

        :param array: the array serial number
        :param source_group: the source group name
        :param snap_name: the name for the snap shot
        :param extra_specs: extra specifications
        """
        LOG.debug("Creating Snap Vx snapshot of storage group: %(srcGroup)s.",
                  {'srcGroup': source_group})

        # Create snapshot
        self.rest.create_storagegroup_snap(
            array, source_group, snap_name, extra_specs)

    def delete_group_replica(self, array, snap_name,
                             source_group_name):
        """Delete the snapshot.

        :param array: the array serial number
        :param snap_name: the name for the snap shot
        :param source_group_name: the source group name
        """
        # Delete snapvx snapshot
        LOG.debug("Deleting Snap Vx snapshot: source group: %(srcGroup)s "
                  "snapshot: %(snap_name)s.",
                  {'srcGroup': source_group_name,
                   'snap_name': snap_name})
        # The check for existence of snapshot has already happened
        # So we just need to delete the snapshot
        self.rest.delete_storagegroup_snap(array, snap_name, source_group_name)

    def link_and_break_replica(self, array, source_group_name,
                               target_group_name, snap_name, extra_specs,
                               delete_snapshot=False):
        """Links a group snap and breaks the relationship.

        :param array: the array serial
        :param source_group_name: the source group name
        :param target_group_name: the target group name
        :param snap_name: the snapshot name
        :param extra_specs: extra specifications
        :param delete_snapshot: delete snapshot flag
        """
        LOG.debug("Linking Snap Vx snapshot: source group: %(srcGroup)s "
                  "targetGroup: %(tgtGroup)s.",
                  {'srcGroup': source_group_name,
                   'tgtGroup': target_group_name})
        # Link the snapshot
        self.rest.modify_storagegroup_snap(
            array, source_group_name, target_group_name, snap_name,
            extra_specs, link=True)
        # Unlink the snapshot
        LOG.debug("Unlinking Snap Vx snapshot: source group: %(srcGroup)s "
                  "targetGroup: %(tgtGroup)s.",
                  {'srcGroup': source_group_name,
                   'tgtGroup': target_group_name})
        self._unlink_group(array, source_group_name,
                           target_group_name, snap_name, extra_specs)
        # Delete the snapshot if necessary
        if delete_snapshot:
            LOG.debug("Deleting Snap Vx snapshot: source group: %(srcGroup)s "
                      "snapshot: %(snap_name)s.",
                      {'srcGroup': source_group_name,
                       'snap_name': snap_name})
            self.rest.delete_storagegroup_snap(array, snap_name,
                                               source_group_name)

    def _unlink_group(
            self, array, source_group_name, target_group_name, snap_name,
            extra_specs):
        """Unlink a target group from it's source group.

        :param array: the array serial number
        :param source_group_name: the source group name
        :param target_group_name: the target device name
        :param snap_name: the snap name
        :param extra_specs: extra specifications
        :returns: return code
        """

        def _unlink_grp():
            """Called at an interval until the synchronization is finished.

            :raises: loopingcall.LoopingCallDone
            """
            retries = kwargs['retries']
            try:
                kwargs['retries'] = retries + 1
                if not kwargs['modify_grp_snap_success']:
                    self.rest.modify_storagegroup_snap(
                        array, source_group_name, target_group_name,
                        snap_name, extra_specs, unlink=True)
                    kwargs['modify_grp_snap_success'] = True
            except exception.VolumeBackendAPIException:
                pass

            if kwargs['retries'] > UNLINK_RETRIES:
                LOG.error("_unlink_grp failed after %(retries)d "
                          "tries.", {'retries': retries})
                raise loopingcall.LoopingCallDone(retvalue=30)
            if kwargs['modify_grp_snap_success']:
                raise loopingcall.LoopingCallDone()

        kwargs = {'retries': 0,
                  'modify_grp_snap_success': False}
        timer = loopingcall.FixedIntervalLoopingCall(_unlink_grp)
        rc = timer.start(interval=UNLINK_INTERVAL).wait()
        return rc
