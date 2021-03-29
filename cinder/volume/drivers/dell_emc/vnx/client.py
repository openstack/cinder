# Copyright (c) 2016 EMC Corporation.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
import time

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils

from cinder import exception
from cinder.i18n import _
from cinder import utils as cinder_utils
from cinder.volume.drivers.dell_emc.vnx import common
from cinder.volume.drivers.dell_emc.vnx import const
from cinder.volume.drivers.dell_emc.vnx import utils

storops = importutils.try_import('storops')
if storops:
    from storops import exception as storops_ex
    from storops.lib import tasks as storops_tasks

LOG = logging.getLogger(__name__)


class Condition(object):
    """Defines some condition checker which are used in wait_until, .etc."""

    @staticmethod
    def is_lun_io_ready(lun):
        utils.update_res_without_poll(lun)
        if not lun.existed:
            return False
        lun_state = lun.state
        if lun_state == common.LUNState.INITIALIZING:
            return False
        elif lun_state in [common.LUNState.READY,
                           common.LUNState.FAULTED]:
            return lun.operation == 'None'
        else:
            # Quick exit wait_until when the lun is other state to avoid
            # long-time timeout.
            msg = (_('Volume %(name)s was created in VNX, '
                   'but in %(state)s state.') % {
                   'name': lun.name, 'state': lun_state})
            raise exception.VolumeBackendAPIException(data=msg)

    @staticmethod
    def is_object_existed(vnx_obj):
        utils.update_res_without_poll(vnx_obj)
        return vnx_obj.existed

    @staticmethod
    def is_lun_ops_ready(lun):
        utils.update_res_without_poll(lun)
        return 'None' == lun.operation

    @staticmethod
    def is_lun_expanded(lun, new_size):
        utils.update_res_without_poll(lun)
        return new_size == lun.total_capacity_gb

    @staticmethod
    def is_mirror_synced(mirror):
        utils.update_res_without_poll(mirror)
        return (
            mirror.secondary_image.state ==
            storops.VNXMirrorImageState.SYNCHRONIZED)


class Client(object):
    def __init__(self, ip, username, password, scope,
                 naviseccli, sec_file, queue_path=None):
        self.naviseccli = naviseccli
        if not storops:
            msg = _('storops Python library is not installed.')
            raise exception.VolumeBackendAPIException(message=msg)
        self.vnx = storops.VNXSystem(ip=ip,
                                     username=username,
                                     password=password,
                                     scope=scope,
                                     naviseccli=naviseccli,
                                     sec_file=sec_file)
        self.sg_cache = {}
        if queue_path:
            self.queue = storops_tasks.PQueue(path=queue_path)
            self.queue.start()
            LOG.info('PQueue[%s] starts now.', queue_path)

    def create_lun(self, pool, name, size, provision,
                   tier, cg_id=None, ignore_thresholds=False,
                   qos_specs=None):
        pool = self.vnx.get_pool(name=pool)
        try:
            with pool.with_no_poll():
                lun = pool.create_lun(lun_name=name,
                                      size_gb=size,
                                      provision=provision,
                                      tier=tier,
                                      ignore_thresholds=ignore_thresholds)
        except storops_ex.VNXLunNameInUseError:
            lun = self.vnx.get_lun(name=name)

        utils.wait_until(condition=Condition.is_lun_io_ready, lun=lun)
        if cg_id:
            cg = self.vnx.get_cg(name=cg_id)
            cg.add_member(lun)
        ioclasses = self.get_ioclass(qos_specs)
        if ioclasses:
            policy, is_new = self.get_running_policy()
            for one in ioclasses:
                one.add_lun(lun)
                policy.add_class(one)
            if is_new:
                policy.run_policy()
        return lun

    def get_lun(self, name=None, lun_id=None):
        return self.vnx.get_lun(name=name, lun_id=lun_id)

    def get_lun_id(self, volume):
        """Retrieves the LUN ID of volume."""
        if volume.provider_location:
            return int(utils.extract_provider_location(
                volume.provider_location, 'id'))
        else:
            # In some cases, cinder will not update volume info in DB with
            # provider_location returned by us. We need to retrieve the id
            # from array. For example, cinder backup-create doesn't use the
            # provider_location returned from create_cloned_volume.
            lun = self.get_lun(name=volume.name)
            return lun.lun_id

    def delete_lun(self, name, force=False, snap_copy=False):
        """Deletes a LUN or mount point."""
        lun = self.get_lun(name=name)
        try:
            # Do not delete the snapshots of the lun.
            lun.delete(force_detach=True, detach_from_sg=force)
            if snap_copy:
                snap = self.vnx.get_snap(name=snap_copy)
                snap.delete()
        except storops_ex.VNXLunNotFoundError as ex:
            LOG.info("LUN %(name)s is already deleted. This message can "
                     "be safely ignored. Message: %(msg)s",
                     {'name': name, 'msg': ex.message})

    def cleanup_async_lun(self, name, force=False):
        """Helper method to cleanup stuff for async migration.

        .. note::
           Only call it when VNXLunUsedByFeatureError occurs
        """
        lun = self.get_lun(name=name)
        self.cleanup_migration(src_id=lun.lun_id)
        lun.delete(force_detach=True, detach_from_sg=force)

    def delay_delete_lun(self, name):
        """Delay the deletion by putting it in a storops queue."""
        self.queue.put(self.vnx.delete_lun, name=name)
        LOG.info("VNX object has been added to queue for later"
                 " deletion: %s", name)

    @cinder_utils.retry(const.VNXLunPreparingError, retries=1,
                        backoff_rate=1)
    def expand_lun(self, name, new_size, poll=True):

        lun = self.get_lun(name=name)

        try:
            lun.poll = poll
            lun.expand(new_size, ignore_thresholds=True)
        except storops_ex.VNXLunExpandSizeError as ex:
            LOG.warning("LUN %(name)s is already expanded. "
                        "Message: %(msg)s.",
                        {'name': name, 'msg': ex.message})

        except storops_ex.VNXLunPreparingError as ex:
            # The error means the operation cannot be performed because the LUN
            # is 'Preparing'. Wait for a while so that the LUN may get out of
            # the transitioning state.
            with excutils.save_and_reraise_exception():
                LOG.warning("LUN %(name)s is not ready for extension: %(msg)s",
                            {'name': name, 'msg': ex.message})

                utils.wait_until(Condition.is_lun_ops_ready, lun=lun)

        utils.wait_until(Condition.is_lun_expanded, lun=lun, new_size=new_size)

    def modify_lun(self):
        pass

    @cinder_utils.retry(retry_param=const.VNXTargetNotReadyError,
                        interval=15,
                        retries=5, backoff_rate=1)
    def migrate_lun(self, src_id, dst_id,
                    rate=const.MIGRATION_RATE_HIGH):
        src = self.vnx.get_lun(lun_id=src_id)
        src.migrate(dst_id, rate)

    def session_finished(self, src_lun):
        session = self.vnx.get_migration_session(src_lun)
        if not session.existed:
            return True
        elif session.current_state in ('FAULTED', 'STOPPED'):
            LOG.warning('Session is %s, need to handled then.',
                        session.current_state)
            return True
        else:
            return False

    def verify_migration(self, src_id, dst_id, dst_wwn):
        """Verify whether migration session finished successfully.

        :param src_id:  source LUN id
        :param dst_id:  destination LUN id
        :param dst_wwn: destination LUN WWN
        :returns Boolean: True or False
        """
        src_lun = self.vnx.get_lun(lun_id=src_id)
        # Sleep 30 seconds to make sure the session starts on the VNX.
        time.sleep(common.INTERVAL_30_SEC)
        utils.wait_until(condition=self.session_finished,
                         interval=common.INTERVAL_30_SEC,
                         src_lun=src_lun)
        new_lun = self.vnx.get_lun(lun_id=dst_id)
        new_wwn = new_lun.wwn
        if not new_wwn or new_wwn != dst_wwn:
            return True
        else:
            return False

    def cleanup_migration(self, src_id, dst_id=None):
        """Invoke when migration meets error.

        :param src_id:  source LUN id
        :param dst_id:  destination LUN id
        """
        # if migration session is still there
        # we need to cancel the session
        session = self.vnx.get_migration_session(src_id)
        src_lun = self.vnx.get_lun(lun_id=src_id)
        if session.existed:
            LOG.warning('Cancelling migration session: '
                        '%(src_id)s -> %(dst_id)s.',
                        {'src_id': src_id,
                         'dst_id': dst_id})
            try:
                src_lun.cancel_migrate()
            except storops_ex.VNXLunNotMigratingError:
                LOG.info('The LUN is not migrating or completed, '
                         'this message can be safely ignored')
            except (storops_ex.VNXLunSyncCompletedError,
                    storops_ex.VNXMigrationError):
                # Wait until session finishes
                self.verify_migration(src_id, session.dest_lu_id, None)

    def create_snapshot(self, lun_id, snap_name, keep_for=None):
        """Creates a snapshot."""

        lun = self.get_lun(lun_id=lun_id)
        try:
            lun.create_snap(
                snap_name, allow_rw=True, auto_delete=False,
                keep_for=keep_for)
        except storops_ex.VNXSnapNameInUseError as ex:
            LOG.warning('Snapshot %(name)s already exists. '
                        'Message: %(msg)s',
                        {'name': snap_name, 'msg': ex.message})

    def delete_snapshot(self, snapshot_name):
        """Deletes a snapshot."""

        snap = self.vnx.get_snap(name=snapshot_name)
        try:
            snap.delete()
        except storops_ex.VNXSnapNotExistsError as ex:
            LOG.warning("Snapshot %(name)s may be deleted already. "
                        "Message: %(msg)s",
                        {'name': snapshot_name, 'msg': ex.message})
        except storops_ex.VNXDeleteAttachedSnapError as ex:
            with excutils.save_and_reraise_exception():
                LOG.warning("Failed to delete snapshot %(name)s "
                            "which is in use. Message: %(msg)s",
                            {'name': snapshot_name, 'msg': ex.message})

    def copy_snapshot(self, snap_name, new_snap_name):
        snap = self.vnx.get_snap(name=snap_name)
        snap.copy(new_name=new_snap_name)

    def create_mount_point(self, lun_name, smp_name):
        lun = self.vnx.get_lun(name=lun_name)
        try:
            return lun.create_mount_point(name=smp_name)
        except storops_ex.VNXLunNameInUseError as ex:
            LOG.warning('Mount point %(name)s already exists. '
                        'Message: %(msg)s',
                        {'name': smp_name, 'msg': ex.message})
            # Ignore the failure that due to retry.
            return self.vnx.get_lun(name=smp_name)

    def attach_snapshot(self, smp_name, snap_name):
        lun = self.vnx.get_lun(name=smp_name)
        try:
            lun.attach_snap(snap=snap_name)
        except storops_ex.VNXSnapAlreadyMountedError as ex:
            LOG.warning("Snapshot %(snap_name)s is attached to "
                        "snapshot mount point %(smp_name)s already. "
                        "Message: %(msg)s",
                        {'snap_name': snap_name,
                         'smp_name': smp_name,
                         'msg': ex.message})

    def detach_snapshot(self, smp_name):
        lun = self.vnx.get_lun(name=smp_name)
        try:
            lun.detach_snap()
        except storops_ex.VNXSnapNotAttachedError as ex:
            LOG.warning("Snapshot mount point %(smp_name)s is not "
                        "currently attached. Message: %(msg)s",
                        {'smp_name': smp_name, 'msg': ex.message})

    def modify_snapshot(self, snap_name, allow_rw=None,
                        auto_delete=None, keep_for=None):
        snap = self.vnx.get_snap(name=snap_name)
        snap.modify(allow_rw=allow_rw, auto_delete=auto_delete,
                    keep_for=None)

    def restore_snapshot(self, lun_id, snap_name):
        lun = self.get_lun(lun_id=lun_id)
        lun.restore_snap(snap_name)

    def create_consistency_group(self, cg_name, lun_id_list=None):
        try:
            cg = self.vnx.create_cg(name=cg_name, members=lun_id_list)
        except storops_ex.VNXConsistencyGroupNameInUseError:
            cg = self.vnx.get_cg(name=cg_name)
        # Wait until cg is found on VNX, or deletion will fail afterwards
        utils.wait_until(Condition.is_object_existed, vnx_obj=cg)
        return cg

    def delete_consistency_group(self, cg_name):
        cg = self.vnx.get_cg(cg_name)
        try:
            cg.delete()
        except storops_ex.VNXConsistencyGroupNotFoundError:
            pass

    def create_cg_snapshot(self, cg_snap_name, cg_name):
        cg = self.vnx.get_cg(cg_name)
        try:
            snap = cg.create_snap(cg_snap_name, allow_rw=True)
        except storops_ex.VNXSnapNameInUseError:
            snap = self.vnx.get_snap(cg_snap_name)
        utils.wait_until(Condition.is_object_existed,
                         vnx_obj=snap)
        return snap

    def delete_cg_snapshot(self, cg_snap_name):
        self.delete_snapshot(cg_snap_name)

    def get_serial(self):
        return self.vnx.serial

    def get_pools(self):
        return self.vnx.get_pool()

    def get_pool(self, name):
        return self.vnx.get_pool(name=name)

    def get_iscsi_targets(self, sp=None, port_id=None, vport_id=None):
        return self.vnx.get_iscsi_port(sp=sp, port_id=port_id,
                                       vport_id=vport_id,
                                       has_ip=True)

    def get_fc_targets(self, sp=None, port_id=None):
        return self.vnx.get_fc_port(sp=sp, port_id=port_id)

    def get_enablers(self):
        return self.vnx.get_ndu()

    def is_fast_enabled(self):
        return self.vnx.is_auto_tiering_enabled()

    def is_compression_enabled(self):
        return self.vnx.is_compression_enabled()

    def is_dedup_enabled(self):
        return self.vnx.is_dedup_enabled()

    def is_fast_cache_enabled(self):
        return self.vnx.is_fast_cache_enabled()

    def is_thin_enabled(self):
        return self.vnx.is_thin_enabled()

    def is_snap_enabled(self):
        return self.vnx.is_snap_enabled()

    def is_mirror_view_enabled(self):
        return self.vnx.is_mirror_view_sync_enabled()

    def get_pool_feature(self):
        return self.vnx.get_pool_feature()

    def lun_has_snapshot(self, lun):
        """Checks lun has snapshot.

        :param lun: instance of VNXLun
        """
        snaps = lun.get_snap()
        return len(snaps) != 0

    def enable_compression(self, lun):
        """Enables compression on lun.

        :param lun: instance of VNXLun
        """
        try:
            lun.enable_compression(ignore_thresholds=True)
        except storops_ex.VNXCompressionAlreadyEnabledError:
            LOG.warning("Compression has already been enabled on %s.",
                        lun.name)

    def get_vnx_enabler_status(self):
        return common.VNXEnablerStatus(
            dedup=self.is_dedup_enabled(),
            compression=self.is_compression_enabled(),
            thin=self.is_thin_enabled(),
            fast=self.is_fast_enabled(),
            snap=self.is_snap_enabled())

    def create_storage_group(self, name):
        try:
            self.sg_cache[name] = self.vnx.create_sg(name)
        except storops_ex.VNXStorageGroupNameInUseError as ex:
            # Ignore the failure due to retry
            LOG.warning('Storage group %(name)s already exists. '
                        'Message: %(msg)s',
                        {'name': name, 'msg': ex.message})
            self.sg_cache[name] = self.vnx.get_sg(name=name)

        return self.sg_cache[name]

    def get_storage_group(self, name):
        """Retrieve the storage group by name.

        Check the storage group instance cache first to save
        CLI call.
        If the specified storage group doesn't exist in the cache,
        try to grab it from CLI.

        :param name: name of the storage group
        :return: storage group instance
        """
        if name not in self.sg_cache:
            self.sg_cache[name] = self.vnx.get_sg(name)
        return self.sg_cache[name]

    def register_initiator(self, storage_group, host, initiator_port_map):
        """Registers the initiators of `host` to the `storage_group`.

        :param storage_group: the storage group object.
        :param host: the ip and name information of the initiator.
        :param initiator_port_map: the dict specifying which initiators are
                                   bound to which ports.
        """
        for (initiator_id, ports_to_bind) in initiator_port_map.items():
            for port in ports_to_bind:
                try:
                    storage_group.connect_hba(port, initiator_id, host.name,
                                              host_ip=host.ip)
                except storops_ex.VNXStorageGroupError as ex:
                    LOG.warning('Failed to set path to port %(port)s for '
                                'initiator %(hba_id)s. Message: %(msg)s',
                                {'port': port, 'hba_id': initiator_id,
                                 'msg': ex.message})

        if any(initiator_port_map.values()):
            LOG.debug('New path set for initiator %(hba_id)s, so update '
                      'storage group with poll.', {'hba_id': initiator_id})
            utils.update_res_with_poll(storage_group)

    def ping_node(self, port, ip_address):
        iscsi_port = self.get_iscsi_targets(sp=port.sp,
                                            port_id=port.port_id,
                                            vport_id=port.vport_id)
        try:
            iscsi_port.ping_node(ip_address, count=1)
            return True
        except storops_ex.VNXPingNodeError:
            return False

    def add_lun_to_sg(self, storage_group, lun, max_retries):
        """Adds the `lun` to `storage_group`."""
        try:
            return storage_group.attach_alu(lun, max_retries)
        except storops_ex.VNXAluAlreadyAttachedError:
            # Ignore the failure due to retry.
            return storage_group.get_hlu(lun)
        except storops_ex.VNXNoHluAvailableError as ex:
            with excutils.save_and_reraise_exception():
                # Reach the max times of retry, fail the attach action.
                LOG.error('Failed to add %(lun)s into %(sg)s after '
                          '%(tried)s tries. Reach the max retry times. '
                          'Message: %(msg)s',
                          {'lun': lun.lun_id, 'sg': storage_group.name,
                           'tried': max_retries, 'msg': ex.message})

    def get_wwn_of_online_fc_ports(self, ports):
        """Returns wwns of online fc ports.

        wwn of a certain port will not be included in the return list when it
        is not present or down.
        """
        wwns = set()
        ports_with_all_info = self.vnx.get_fc_port()
        for po in ports:
            online_list = [p for p in ports_with_all_info if p == po and
                           p.link_status == 'Up' and p.port_status == 'Online']

            wwns.update([p.wwn for p in online_list])
        return list(wwns)

    def sg_has_lun_attached(self, sg):
        return bool(sg.get_alu_hlu_map())

    def deregister_initiators(self, initiators):
        if not isinstance(initiators, list):
            initiators = [initiators]
        for initiator_uid in initiators:
            try:
                self.vnx.delete_hba(initiator_uid)
            except AttributeError:
                self.vnx.remove_hba(initiator_uid)

    def update_consistencygroup(self, cg, lun_ids_to_add, lun_ids_to_remove):
        lun_ids_in_cg = (set([lu.lun_id for lu in cg.lun_list]) if cg.lun_list
                         else set())

        # lun_ids_to_add and lun_ids_to_remove never overlap.
        lun_ids_updated = ((lun_ids_in_cg | set(lun_ids_to_add)) -
                           set(lun_ids_to_remove))

        if lun_ids_updated:
            cg.replace_member(*[self.get_lun(lun_id=lun_id)
                                for lun_id in lun_ids_updated])
        else:
            # Need to remove all LUNs from cg. However, replace_member cannot
            # handle empty list. So use delete_member.
            cg.delete_member(*[self.get_lun(lun_id=lun_id)
                               for lun_id in lun_ids_in_cg])

    def get_cg(self, name):
        return self.vnx.get_cg(name=name)

    def get_available_ip(self):
        return self.vnx.alive_sp_ip

    def get_mirror(self, mirror_name):
        return self.vnx.get_mirror_view(mirror_name)

    def create_mirror(self, mirror_name, primary_lun_id):
        src_lun = self.vnx.get_lun(lun_id=primary_lun_id)
        try:
            mv = self.vnx.create_mirror_view(mirror_name, src_lun)
        except storops_ex.VNXMirrorNameInUseError:
            mv = self.vnx.get_mirror_view(mirror_name)
        return mv

    def delete_mirror(self, mirror_name):
        mv = self.vnx.get_mirror_view(mirror_name)
        try:
            mv.delete()
        except storops_ex.VNXMirrorNotFoundError:
            pass

    def add_image(self, mirror_name, sp_ip, secondary_lun_id):
        mv = self.vnx.get_mirror_view(mirror_name)
        mv.add_image(sp_ip, secondary_lun_id)
        # Secondary image info usually did not appear, so
        # here add a poll to update.
        utils.update_res_with_poll(mv)
        utils.wait_until(Condition.is_mirror_synced, mirror=mv)

    def remove_image(self, mirror_name):
        mv = self.vnx.get_mirror_view(mirror_name)
        mv.remove_image()

    def fracture_image(self, mirror_name):
        mv = self.vnx.get_mirror_view(mirror_name)
        mv.fracture_image()

    def sync_image(self, mirror_name):
        mv = self.vnx.get_mirror_view(mirror_name)
        mv.sync_image()
        utils.wait_until(Condition.is_mirror_synced, mirror=mv)

    def promote_image(self, mirror_name):
        mv = self.vnx.get_mirror_view(mirror_name)
        mv.promote_image()

    def create_mirror_group(self, group_name):
        try:
            mg = self.vnx.create_mirror_group(group_name)
        except storops_ex.VNXMirrorGroupNameInUseError:
            mg = self.vnx.get_mirror_group(group_name)
        return mg

    def delete_mirror_group(self, group_name):
        mg = self.vnx.get_mirror_group(group_name)
        try:
            mg.delete()
        except storops_ex.VNXMirrorGroupNotFoundError:
            LOG.info('Mirror group %s was already deleted.', group_name)

    def add_mirror(self, group_name, mirror_name):
        mg = self.vnx.get_mirror_group(group_name)
        mv = self.vnx.get_mirror_view(mirror_name)
        try:
            mg.add_mirror(mv)
        except storops_ex.VNXMirrorGroupAlreadyMemberError:
            LOG.info('Mirror %(mirror)s is already a member of %(group)s',
                     {'mirror': mirror_name, 'group': group_name})
        return mg

    def remove_mirror(self, group_name, mirror_name):
        mg = self.vnx.get_mirror_group(group_name)
        mv = self.vnx.get_mirror_view(mirror_name)
        try:
            mg.remove_mirror(mv)
        except storops_ex.VNXMirrorGroupMirrorNotMemberError:
            LOG.info('Mirror %(mirror)s is not a member of %(group)s',
                     {'mirror': mirror_name, 'group': group_name})

    def promote_mirror_group(self, group_name):
        mg = self.vnx.get_mirror_group(group_name)
        try:
            mg.promote_group()
        except storops_ex.VNXMirrorGroupAlreadyPromotedError:
            LOG.info('Mirror group %s was already promoted.', group_name)
        return mg

    def sync_mirror_group(self, group_name):
        mg = self.vnx.get_mirror_group(group_name)
        mg.sync_group()

    def fracture_mirror_group(self, group_name):
        mg = self.vnx.get_mirror_group(group_name)
        mg.fracture_group()

    def get_pool_name(self, lun_name):
        lun = self.get_lun(name=lun_name)
        utils.update_res_without_poll(lun)
        return lun.pool_name

    def get_ioclass(self, qos_specs):
        ioclasses = []
        if qos_specs is not None:
            prefix = qos_specs['id']
            max_bws = qos_specs[common.QOS_MAX_BWS]
            max_iops = qos_specs[common.QOS_MAX_IOPS]
            if max_bws:
                name = '%(prefix)s-bws-%(max)s' % {
                    'prefix': prefix, 'max': max_bws}
                class_bws = self.vnx.get_ioclass(name=name)
                if not class_bws.existed:
                    class_bws = self.create_ioclass_bws(name,
                                                        max_bws)
                ioclasses.append(class_bws)
            if max_iops:
                name = '%(prefix)s-iops-%(max)s' % {
                    'prefix': prefix, 'max': max_iops}
                class_iops = self.vnx.get_ioclass(name=name)
                if not class_iops.existed:
                    class_iops = self.create_ioclass_iops(name,
                                                          max_iops)
                ioclasses.append(class_iops)
        return ioclasses

    def create_ioclass_iops(self, name, max_iops):
        """Creates a ioclass by IOPS."""
        max_iops = int(max_iops)
        ctrl_method = storops.VNXCtrlMethod(
            method=storops.VNXCtrlMethod.LIMIT_CTRL,
            metric='tt', value=max_iops)
        ioclass = self.vnx.create_ioclass(name=name, iotype='rw',
                                          ctrlmethod=ctrl_method)
        return ioclass

    def create_ioclass_bws(self, name, max_bws):
        """Creates a ioclass by bandwidth in MiB."""
        max_bws = int(max_bws)
        ctrl_method = storops.VNXCtrlMethod(
            method=storops.VNXCtrlMethod.LIMIT_CTRL,
            metric='bw', value=max_bws)
        ioclass = self.vnx.create_ioclass(name=name, iotype='rw',
                                          ctrlmethod=ctrl_method)
        return ioclass

    def create_policy(self, policy_name):
        """Creates the policy and starts it."""
        policy = self.vnx.get_policy(name=policy_name)
        if not policy.existed:
            LOG.info('Creating the policy: %s', policy_name)
            policy = self.vnx.create_policy(name=policy_name)
        return policy

    def get_running_policy(self):
        """Returns the only running/measuring policy on VNX.

        .. note: VNX only allows one running policy.
        """
        policies = self.vnx.get_policy()
        policies = list(filter(lambda p: p.state == "Running" or p.state ==
                        "Measuring", policies))
        if len(policies) >= 1:
            return policies[0], False
        else:
            return self.create_policy("vnx_policy"), True

    def add_lun_to_ioclass(self, ioclass_name, lun_id):
        ioclass = self.vnx.get_ioclass(name=ioclass_name)
        ioclass.add_lun(lun_id)

    def filter_sg(self, attached_lun_id):
        return self.vnx.get_sg().shadow_copy(attached_lun=attached_lun_id)

    def set_max_luns_per_sg(self, max_luns):
        """Sets max LUNs per storage group."""
        storops.vnx.resource.sg.VNXStorageGroup.set_max_luns_per_sg(max_luns)
        LOG.info('Set max LUNs per storage group to %s.', max_luns)
