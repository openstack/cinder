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

import time

from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import units

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.dell_emc.powermax import utils

LOG = logging.getLogger(__name__)

WRITE_DISABLED = "Write Disabled"
UNLINK_INTERVAL = 15
UNLINK_RETRIES = 30


class PowerMaxProvision(object):
    """Provisioning Class for Dell EMC PowerMax volume drivers.

    It supports VMAX 3, All Flash and PowerMax arrays.
    """
    def __init__(self, rest):
        self.utils = utils.PowerMaxUtils()
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

        @coordination.synchronized("emc-sg-{storage_group}-{array}")
        def do_create_storage_group(storage_group, array):
            # Check if storage group has been recently created
            storagegroup = self.rest.get_storage_group(
                array, storagegroup_name)
            if storagegroup is None:
                storagegroup = self.rest.create_storage_group(
                    array, storage_group, srp, slo, workload, extra_specs,
                    do_disable_compression)

                LOG.debug("Create storage group took: %(delta)s H:MM:SS.",
                          {'delta': self.utils.get_time_delta(start_time,
                                                              time.time())})
                LOG.info("Storage group %(sg)s created successfully.",
                         {'sg': storagegroup_name})
            else:
                LOG.info("Storage group %(sg)s already exists.",
                         {'sg': storagegroup_name})
            return storagegroup

        return do_create_storage_group(storagegroup_name, array)

    def create_volume_from_sg(self, array, volume_name, storagegroup_name,
                              volume_size, extra_specs, rep_info=None):
        """Create a new volume in the given storage group.

        :param array: the array serial number
        :param volume_name: the volume name -- string
        :param storagegroup_name: the storage group name
        :param volume_size: volume size -- string
        :param extra_specs: extra specifications
        :param rep_info: replication session info dict -- optional
        :returns: volume info -- dict
        """
        @coordination.synchronized("emc-sg-{storage_group}-{array}")
        def do_create_volume_from_sg(storage_group, array):
            start_time = time.time()

            if rep_info and rep_info.get('initial_device_list', False):
                local_device_list = self.rest.get_volume_list(
                    extra_specs['array'],
                    {'storageGroupId': storagegroup_name})
                rep_info['initial_device_list'] = local_device_list

            volume_dict = self.rest.create_volume_from_sg(
                array, volume_name, storage_group,
                volume_size, extra_specs, rep_info)

            LOG.debug("Create volume from storage group "
                      "took: %(delta)s H:MM:SS.",
                      {'delta': self.utils.get_time_delta(start_time,
                                                          time.time())})
            return volume_dict
        return do_create_volume_from_sg(storagegroup_name, array)

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
                             snap_name, extra_specs, ttl=0):
        """Create a snapVx of a volume.

        :param array: the array serial number
        :param source_device_id: source volume device id
        :param snap_name: the snapshot name
        :param extra_specs: the extra specifications
        :param ttl: time to live in hours, defaults to 0
        """
        @coordination.synchronized("emc-snapvx-{src_device_id}")
        def do_create_volume_snap(src_device_id):
            start_time = time.time()
            LOG.debug("Create Snap Vx snapshot of: %(source)s.",
                      {'source': src_device_id})

            self.rest.create_volume_snap(
                array, snap_name, src_device_id, extra_specs, ttl)
            LOG.debug("Create volume snapVx took: %(delta)s H:MM:SS.",
                      {'delta': self.utils.get_time_delta(start_time,
                                                          time.time())})

        do_create_volume_snap(source_device_id)

    def create_volume_replica(
            self, array, source_device_id, target_device_id,
            snap_name, extra_specs, create_snap=False, copy_mode=False):
        """Create a snap vx of a source and copy to a target.

        :param array: the array serial number
        :param source_device_id: source volume device id
        :param target_device_id: target volume device id
        :param snap_name: the name for the snap shot
        :param extra_specs: extra specifications
        :param create_snap: Flag for create snapvx
        :param copy_mode: If copy mode should be used for SnapVX target links
        """
        start_time = time.time()
        if create_snap:
            # We are creating a temporary snapshot. Specify a ttl of 1 hour
            self.create_volume_snapvx(array, source_device_id,
                                      snap_name, extra_specs, ttl=1)
        # Link source to target

        @coordination.synchronized("emc-snapvx-{src_device_id}")
        def do_modify_volume_snap(src_device_id):
            self.rest.modify_volume_snap(
                array, src_device_id, target_device_id, snap_name,
                extra_specs, link=True, copy=copy_mode)

        do_modify_volume_snap(source_device_id)

        LOG.debug("Create element replica took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(start_time,
                                                      time.time())})

    def unlink_snapvx_tgt_volume(
            self, array, target_device_id, source_device_id, snap_name,
            extra_specs, snap_id, loop=True):
        """Unlink a snapshot from its target volume.

        :param array: the array serial number
        :param source_device_id: source volume device id
        :param target_device_id: target volume device id
        :param snap_name: the name for the snap shot
        :param extra_specs: extra specifications
        :param snap_id: the unique snap id of the SnapVX
        :param loop: if looping call is required for handling retries
        """
        @coordination.synchronized("emc-snapvx-{src_device_id}")
        def do_unlink_volume(src_device_id):
            LOG.debug("Break snap vx link relationship between: %(src)s "
                      "and: %(tgt)s.",
                      {'src': src_device_id, 'tgt': target_device_id})

            self._unlink_volume(array, src_device_id, target_device_id,
                                snap_name, extra_specs, snap_id=snap_id,
                                list_volume_pairs=None, loop=loop)

        do_unlink_volume(source_device_id)

    def _unlink_volume(
            self, array, source_device_id, target_device_id, snap_name,
            extra_specs, snap_id=None, list_volume_pairs=None, loop=True):
        """Unlink a target volume from its source volume.

        :param array: the array serial number
        :param source_device_id: the source device id
        :param target_device_id: the target device id
        :param snap_name: the snap name
        :param extra_specs: extra specifications
        :param snap_id: the unique snap id of the SnapVX
        :param list_volume_pairs: list of volume pairs, optional
        :param loop: if looping call is required for handling retries
        :returns: return code
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
                        extra_specs, snap_id=snap_id, unlink=True,
                        list_volume_pairs=list_volume_pairs)
                    kwargs['modify_vol_success'] = True
            except exception.VolumeBackendAPIException:
                pass

            if kwargs['retries'] > UNLINK_RETRIES:
                LOG.error("_unlink_volume failed after %(retries)d "
                          "tries.", {'retries': retries})
                raise loopingcall.LoopingCallDone(retvalue=30)
            if kwargs['modify_vol_success']:
                raise loopingcall.LoopingCallDone()

        if not loop:
            self.rest.modify_volume_snap(
                array, source_device_id, target_device_id, snap_name,
                extra_specs, snap_id=snap_id, unlink=True,
                list_volume_pairs=list_volume_pairs)
        else:
            kwargs = {'retries': 0,
                      'modify_vol_success': False}
            timer = loopingcall.FixedIntervalLoopingCall(_unlink_vol)
            rc = timer.start(interval=UNLINK_INTERVAL).wait()
            return rc

    def delete_volume_snap(self, array, snap_name,
                           source_device_ids, snap_id=None, restored=False):
        """Delete a snapVx snapshot of a volume.

        :param array: the array serial number
        :param snap_name: the snapshot name
        :param source_device_ids: the source device ids
        :param snap_id: the unique snap id of the SnapVX
        :param restored: Flag to indicate if restored session is being deleted
        """
        @coordination.synchronized("emc-snapvx-{src_device_id}")
        def do_delete_volume_snap(src_device_id):
            LOG.debug("Delete SnapVx: %(snap_name)s for source %(src)s and "
                      "devices %(devs)s.",
                      {'snap_name': snap_name, 'src': src_device_id,
                       'devs': source_device_ids})
            self.rest.delete_volume_snap(
                array, snap_name, source_device_ids, snap_id=snap_id,
                restored=restored)

        device_id = source_device_ids[0] if isinstance(
            source_device_ids, list) else source_device_ids

        if snap_id is None:
            snap_id = self.rest.get_snap_id(array, device_id, snap_name)
        do_delete_volume_snap(device_id)

    def is_restore_complete(self, array, source_device_id,
                            snap_name, snap_id, extra_specs):
        """Check and wait for a restore to complete

        :param array: the array serial number
        :param source_device_id: source device id
        :param snap_name: snapshot name
        :param snap_id: unique snap id
        :param extra_specs: extra specification
        :returns: bool
        """

        def _wait_for_restore():
            """Called at an interval until the restore is finished.

            :raises: loopingcall.LoopingCallDone
            :raises: VolumeBackendAPIException
            """
            retries = kwargs['retries']
            try:
                kwargs['retries'] = retries + 1
                if not kwargs['wait_for_restore_called']:
                    if self._is_restore_complete(
                            array, source_device_id, snap_name, snap_id):
                        kwargs['wait_for_restore_called'] = True
            except Exception:
                exception_message = (_("Issue encountered waiting for "
                                       "restore."))
                LOG.exception(exception_message)
                raise exception.VolumeBackendAPIException(
                    message=exception_message)

            if kwargs['wait_for_restore_called']:
                raise loopingcall.LoopingCallDone()
            if kwargs['retries'] > int(extra_specs[utils.RETRIES]):
                LOG.error("_wait_for_restore failed after %(retries)d "
                          "tries.", {'retries': retries})
                raise loopingcall.LoopingCallDone(
                    retvalue=int(extra_specs[utils.RETRIES]))

        kwargs = {'retries': 0,
                  'wait_for_restore_called': False}
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_restore)
        rc = timer.start(interval=int(extra_specs[utils.INTERVAL])).wait()
        return rc

    def _is_restore_complete(
            self, array, source_device_id, snap_name, snap_id):
        """Helper function to check if restore is complete.

        :param array: the array serial number
        :param source_device_id: source device id
        :param snap_name: the snapshot name
        :param snap_id: unique snap id
        :returns: restored -- bool
        """
        restored = False
        snap_details = self.rest.get_volume_snap(
            array, source_device_id, snap_name, snap_id)
        if snap_details:
            linked_devices = snap_details.get("linkedDevices", [])
            for linked_device in linked_devices:
                if ('targetDevice' in linked_device and
                        source_device_id == linked_device['targetDevice']):
                    if ('state' in linked_device and
                            linked_device['state'] == "Restored"):
                        restored = True
        return restored

    def delete_temp_volume_snap(self, array, snap_name,
                                source_device_id, snap_id):
        """Delete the temporary snapshot created for clone operations.

        There can be instances where the source and target both attempt to
        delete a temp snapshot simultaneously, so we must lock the snap and
        then double check it is on the array.
        :param array: the array serial number
        :param snap_name: the snapshot name
        :param source_device_id: the source device id
        :param snap_id: the unique snap id of the SnapVX
        """
        snapvx = self.rest.get_volume_snap(
            array, source_device_id, snap_name, snap_id)
        if snapvx:
            self.delete_volume_snap(
                array, snap_name, source_device_id, snap_id=snap_id,
                restored=False)

    def delete_volume_snap_check_for_links(
            self, array, snap_name, source_devices, extra_specs, snap_id):
        """Check if a snap has any links before deletion.

        If a snapshot has any links, break the replication relationship
        before deletion.
        :param array: the array serial number
        :param snap_name: the snapshot name
        :param source_devices: the source device ids
        :param extra_specs: the extra specifications
        :param snap_id: the unique snap id of the SnapVX
        """
        list_device_pairs = []
        if not isinstance(source_devices, list):
            source_devices = [source_devices]
        for source_device in source_devices:
            LOG.debug("Check for linked devices to SnapVx: %(snap_name)s "
                      "for volume %(vol)s.",
                      {'vol': source_device, 'snap_name': snap_name})
            linked_list = self.rest.get_snap_linked_device_list(
                array, source_device, snap_name, snap_id)
            if len(linked_list) == 1:
                target_device = linked_list[0]['targetDevice']
                list_device_pairs.append((source_device, target_device))
            else:
                for link in linked_list:
                    # If a single source volume has multiple targets,
                    # we must unlink each target individually
                    target_device = link['targetDevice']
                    self._unlink_volume(
                        array, source_device, target_device, snap_name,
                        extra_specs, snap_id=snap_id)
        if list_device_pairs:
            self._unlink_volume(
                array, "", "", snap_name, extra_specs, snap_id=snap_id,
                list_volume_pairs=list_device_pairs)
        if source_devices:
            self.delete_volume_snap(
                array, snap_name, source_devices, snap_id, restored=False)

    def extend_volume(self, array, device_id, new_size, extra_specs,
                      rdf_group=None):
        """Extend a volume.

        :param array: the array serial number
        :param device_id: the volume device id
        :param new_size: the new size (GB)
        :param extra_specs: the extra specifications
        :param rdf_group: the rdf group number, if required
        :returns: status_code
        """
        start_time = time.time()
        if rdf_group:
            @coordination.synchronized('emc-rg-{rdf_group}')
            def _extend_replicated_volume(rdf_group):
                self.rest.extend_volume(array, device_id,
                                        new_size, extra_specs, rdf_group)
            _extend_replicated_volume(rdf_group)
        else:
            self.rest.extend_volume(array, device_id, new_size, extra_specs)
            LOG.debug("Extend PowerMax/VMAX volume took: %(delta)s H:MM:SS.",
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
            srp_capacity = srp_details['srp_capacity']
            total_capacity_gb = srp_capacity['usable_total_tb'] * units.Ki
            try:
                used_capacity_gb = srp_capacity['usable_used_tb'] * units.Ki
                remaining_capacity_gb = float(
                    total_capacity_gb - used_capacity_gb)
            except KeyError:
                LOG.error("Unable to retrieve remaining_capacity_gb.")
            subscribed_capacity_gb = (
                srp_capacity['subscribed_total_tb'] * units.Ki)
            array_reserve_percent = srp_details['reserved_cap_percent']
        except KeyError:
            pass

        return (total_capacity_gb, remaining_capacity_gb,
                subscribed_capacity_gb, array_reserve_percent)

    def verify_slo_workload(
            self, array, slo, workload, is_next_gen=None, array_model=None):
        """Check if SLO and workload values are valid.

        :param array: the array serial number
        :param slo: Service Level Object e.g bronze
        :param workload: workload e.g DSS
        :param is_next_gen: can be None

        :returns: boolean
        """
        is_valid_slo, is_valid_workload = False, False

        if workload and workload.lower() == 'none':
            workload = None

        if not workload:
            is_valid_workload = True

        if slo and slo.lower() == 'none':
            slo = None

        if is_next_gen or is_next_gen is None:
            array_model, is_next_gen = self.rest.get_array_model_info(
                array)
        valid_slos = self.rest.get_slo_list(array, is_next_gen, array_model)

        valid_workloads = self.rest.get_workload_settings(array, is_next_gen)
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
            LOG.warning(
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
                workload = 'NONE' if self.rest.is_next_gen_array(array) else (
                    storage_group['workload'])
            except KeyError:
                pass
        else:
            exception_message = (_(
                "Could not retrieve storage group %(sg_name)s. ") %
                {'sg_name': sg_name})
            LOG.error(exception_message)
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        return '%(slo)s+%(workload)s' % {'slo': slo, 'workload': workload}

    @coordination.synchronized('emc-rg-{rdf_group}')
    def break_rdf_relationship(self, array, device_id, sg_name,
                               rdf_group, rep_extra_specs, state):
        """Break the rdf relationship between a pair of devices.

        Resuming replication after suspending is necessary where this function
        is called from. Doing so in here will disrupt the ability to perform
        further actions on the RDFG without suspending again.

        :param array: the array serial number
        :param device_id: the source device id
        :param sg_name: storage group
        :param rdf_group: the rdf group number
        :param rep_extra_specs: replication extra specs
        :param state: the state of the rdf pair
        """
        LOG.info("Suspending RDF group %(rdf)s to delete source device "
                 "%(dev)s RDF pair.", {'rdf': rdf_group, 'dev': device_id})

        if state.lower() == utils.RDF_SYNCINPROG_STATE:
            self.rest.wait_for_rdf_pair_sync(
                array, rdf_group, device_id, rep_extra_specs)
        if state.lower() != utils.RDF_SUSPENDED_STATE:
            self.rest.srdf_suspend_replication(
                array, sg_name, rdf_group, rep_extra_specs)

        self.rest.srdf_delete_device_pair(array, rdf_group, device_id)

    def get_or_create_volume_group(self, array, group, extra_specs):
        """Get or create a volume group.

        Sometimes it may be necessary to recreate a volume group on the
        backend - for example, when the last member volume has been removed
        from the group, but the cinder group object has not been deleted.
        :param array: the array serial number
        :param group: the group object
        :param extra_specs: the extra specifications
        :returns: group name
        """
        vol_grp_name = self.utils.update_volume_group_name(group)
        return self.get_or_create_group(array, vol_grp_name, extra_specs)

    def get_or_create_group(self, array, group_name, extra_specs):
        """Get or create a generic volume group.

        :param array: the array serial number
        :param group_name: the group name
        :param extra_specs: the extra specifications
        :returns: group name
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

    def delete_group_replica(self, array, snap_name, source_group_name):
        """Delete the snapshot.

        :param array: the array serial number
        :param snap_name: the name for the snap shot
        :param source_group_name: the source group name
        """
        LOG.debug("Deleting Snap Vx snapshot: source group: %(srcGroup)s "
                  "snapshot: %(snap_name)s.",
                  {'srcGroup': source_group_name, 'snap_name': snap_name})
        snap_id_list = self.rest.get_storage_group_snap_id_list(
            array, source_group_name, snap_name)
        if snap_id_list:
            if not self.rest.is_snap_id:
                snap_id_list.sort(reverse=True)
            for snap_id in snap_id_list:
                self.rest.delete_storagegroup_snap(
                    array, source_group_name, snap_name, snap_id)
        else:
            LOG.debug("Unable to get snap ids for: %(srcGroup)s.",
                      {'srcGroup': source_group_name})

    def link_and_break_replica(self, array, source_group_name,
                               target_group_name, snap_name, extra_specs,
                               list_volume_pairs, delete_snapshot=False,
                               snap_id=None):
        """Links a group snap and breaks the relationship.

        :param array: the array serial
        :param source_group_name: the source group name
        :param target_group_name: the target group name
        :param snap_name: the snapshot name
        :param extra_specs: extra specifications
        :param list_volume_pairs: the list of volume pairs
        :param delete_snapshot: delete snapshot flag
        :param snap_id: the unique snapVx identifier
        """
        LOG.debug("Linking Snap Vx snapshot: source group: %(srcGroup)s "
                  "targetGroup: %(tgtGroup)s.",
                  {'srcGroup': source_group_name,
                   'tgtGroup': target_group_name})
        # Link the snapshot
        self.rest.modify_volume_snap(
            array, None, None, snap_name, extra_specs, snap_id=snap_id,
            link=True, list_volume_pairs=list_volume_pairs)
        # Unlink the snapshot
        LOG.debug("Unlinking Snap Vx snapshot: source group: %(srcGroup)s "
                  "targetGroup: %(tgtGroup)s.",
                  {'srcGroup': source_group_name,
                   'tgtGroup': target_group_name})
        self._unlink_volume(
            array, None, None, snap_name, extra_specs, snap_id=snap_id,
            list_volume_pairs=list_volume_pairs)
        # Delete the snapshot if necessary
        if delete_snapshot:
            LOG.debug("Deleting Snap Vx snapshot: source group: %(srcGroup)s "
                      "snapshot: %(snap_name)s.",
                      {'srcGroup': source_group_name,
                       'snap_name': snap_name})
            source_devices = [a for a, b in list_volume_pairs]
            self.delete_volume_snap(array, snap_name, source_devices)

    def revert_volume_snapshot(self, array, source_device_id,
                               snap_name, snap_id, extra_specs):
        """Revert a volume snapshot

        :param array: the array serial number
        :param source_device_id: device id of the source
        :param snap_name: snapvx snapshot name
        :param snap_id: the unique snap identifier
        :param extra_specs: the extra specifications
        """
        start_time = time.time()
        try:
            self.rest.modify_volume_snap(
                array, source_device_id, "", snap_name, extra_specs,
                snap_id=snap_id, restore=True)
        except exception.VolumeBackendAPIException as ex:
            if utils.REVERT_SS_EXC in ex.message:
                exception_message = _(
                    "Link must be fully copied for this operation to proceed. "
                    "Please reset the volume state from error to available "
                    "and wait for awhile before attempting another "
                    "revert to snapshot operation. You may want to delete "
                    "the latest snapshot taken in this revert to snapshot "
                    "operation, as you will only be able to revert to the "
                    "last snapshot.")
            else:
                exception_message = (_(
                    "Revert to snapshot failed with exception "
                    "%(e)s.") % {'e': ex})
            raise exception.VolumeBackendAPIException(
                message=exception_message)
        LOG.debug("Restore volume snapshot took: %(delta)s H:MM:SS.",
                  {'delta': self.utils.get_time_delta(start_time,
                                                      time.time())})
