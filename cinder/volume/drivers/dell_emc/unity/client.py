# Copyright (c) 2016 Dell Inc. or its subsidiaries.
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

from oslo_log import log
from oslo_utils import excutils
from oslo_utils import importutils

storops = importutils.try_import('storops')
if storops:
    from storops import exception as storops_ex
else:
    # Set storops_ex to be None for unit test
    storops_ex = None

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.dell_emc.unity import utils

LOG = log.getLogger(__name__)


class UnityClient(object):
    def __init__(self, host, username, password, verify_cert=True):
        if storops is None:
            msg = _('Python package storops is not installed which '
                    'is required to run Unity driver.')
            raise exception.VolumeBackendAPIException(data=msg)
        self._system = None
        self.host = host
        self.username = username
        self.password = password
        self.verify_cert = verify_cert
        self.host_cache = {}

    @property
    def system(self):
        if self._system is None:
            self._system = storops.UnitySystem(
                host=self.host, username=self.username, password=self.password,
                verify=self.verify_cert)
        return self._system

    def get_serial(self):
        return self.system.serial_number

    def create_lun(self, name, size, pool, description=None,
                   io_limit_policy=None, is_thin=None,
                   is_compressed=None, cg_name=None, tiering_policy=None):
        """Creates LUN on the Unity system.

        :param name: lun name
        :param size: lun size in GiB
        :param pool: UnityPool object represent to pool to place the lun
        :param description: lun description
        :param io_limit_policy: io limit on the LUN
        :param is_thin: if False, a thick LUN will be created
        :param is_compressed: is compressed LUN enabled
        :param tiering_policy: tiering policy for the LUN
        :param cg_name: the name of cg to join if any
        :return: UnityLun object
        """
        try:
            lun = pool.create_lun(lun_name=name, size_gb=size,
                                  description=description,
                                  io_limit_policy=io_limit_policy,
                                  is_thin=is_thin,
                                  is_compression=is_compressed,
                                  tiering_policy=tiering_policy)
        except storops_ex.UnityLunNameInUseError:
            LOG.debug("LUN %s already exists. Return the existing one.",
                      name)
            lun = self.system.get_lun(name=name)
        return lun

    def thin_clone(self, lun_or_snap, name, io_limit_policy=None,
                   description=None, new_size_gb=None):
        try:
            lun = lun_or_snap.thin_clone(
                name=name, io_limit_policy=io_limit_policy,
                description=description)
        except storops_ex.UnityLunNameInUseError:
            LOG.debug("LUN(thin clone) %s already exists. "
                      "Return the existing one.", name)
            lun = self.system.get_lun(name=name)
        if new_size_gb is not None and new_size_gb > lun.total_size_gb:
            lun = self.extend_lun(lun.get_id(), new_size_gb)
        return lun

    def delete_lun(self, lun_id):
        """Deletes LUN on the Unity system.

        :param lun_id: id of the LUN
        """
        try:
            lun = self.system.get_lun(_id=lun_id)
        except storops_ex.UnityResourceNotFoundError:
            LOG.debug("Cannot get LUN %s from unity. Do nothing.", lun_id)
            return

        def _delete_lun_if_exist(force_snap_delete=False):
            """Deletes LUN, skip if it doesn't exist."""
            try:
                lun.delete(force_snap_delete=force_snap_delete)
            except storops_ex.UnityResourceNotFoundError:
                LOG.debug("LUN %s doesn't exist. Deletion is not needed.",
                          lun_id)

        try:
            _delete_lun_if_exist()
        except storops_ex.UnityDeleteLunInReplicationError:
            LOG.info("LUN %s is participating in replication sessions. "
                     "Delete replication sessions first",
                     lun_id)
            self.delete_lun_replications(lun_id)

            # It could fail if not pass in force_snap_delete when
            # deleting the lun immediately after
            # deleting the replication sessions.
            _delete_lun_if_exist(force_snap_delete=True)

    def delete_lun_replications(self, lun_id):
        LOG.debug("Deleting all the replication sessions which are from "
                  "lun %s", lun_id)
        try:
            rep_sessions = self.system.get_replication_session(
                src_resource_id=lun_id)
        except storops_ex.UnityResourceNotFoundError:
            LOG.debug("No replication session found from lun %s. Do nothing.",
                      lun_id)
        else:
            for session in rep_sessions:
                try:
                    session.delete()
                except storops_ex.UnityResourceNotFoundError:
                    LOG.debug("Replication session %s doesn't exist. "
                              "Skip the deletion.", session.get_id())

    def get_lun(self, lun_id=None, name=None):
        """Gets LUN on the Unity system.

        :param lun_id: id of the LUN
        :param name: name of the LUN
        :return: `UnityLun` object
        """
        lun = None
        if lun_id is None and name is None:
            LOG.warning(
                "Both lun_id and name are None to get LUN. Return None.")
        else:
            try:
                lun = self.system.get_lun(_id=lun_id, name=name)
            except storops_ex.UnityResourceNotFoundError:
                LOG.warning(
                    "LUN id=%(id)s, name=%(name)s doesn't exist.",
                    {'id': lun_id, 'name': name})
        return lun

    def extend_lun(self, lun_id, size_gib):
        lun = self.system.get_lun(lun_id)
        try:
            lun.total_size_gb = size_gib
        except storops_ex.UnityNothingToModifyError:
            LOG.debug("LUN %s is already expanded. LUN expand is not needed.",
                      lun_id)
        return lun

    def migrate_lun(self, lun_id, dest_pool_id, dest_provision=None):
        # dest_provision possible value ('thin', 'thick', 'compressed')
        lun = self.system.get_lun(lun_id)
        dest_pool = self.system.get_pool(dest_pool_id)
        is_thin = True if dest_provision == 'thin' else None
        if dest_provision == 'compressed':
            # compressed needs work with thin
            is_compressed = True
            is_thin = True
        else:
            is_compressed = False
        if dest_provision == 'thick':
            # thick needs work with uncompressed
            is_thin = False
            is_compressed = False
        return lun.migrate(dest_pool, is_compressed=is_compressed,
                           is_thin=is_thin)

    def get_pools(self):
        """Gets all storage pools on the Unity system.

        :return: list of UnityPool object
        """
        return self.system.get_pool()

    def create_snap(self, src_lun_id, name=None):
        """Creates a snapshot of LUN on the Unity system.

        :param src_lun_id: the source LUN ID of the snapshot.
        :param name: the name of the snapshot. The Unity system will give one
                     if `name` is None.
        """
        try:
            lun = self.get_lun(lun_id=src_lun_id)
            snap = lun.create_snap(name, is_auto_delete=False)
        except storops_ex.UnitySnapNameInUseError as err:
            LOG.debug(
                "Snap %(snap_name)s already exists on LUN %(lun_id)s. "
                "Return the existing one. Message: %(err)s",
                {'snap_name': name,
                 'lun_id': src_lun_id,
                 'err': err})
            snap = self.get_snap(name=name)
        return snap

    @staticmethod
    def delete_snap(snap):
        if snap is None:
            LOG.debug("Snap to delete is None, skipping deletion.")
            return

        try:
            snap.delete()
        except storops_ex.UnityResourceNotFoundError as err:
            LOG.debug("Snap %(snap_name)s may be deleted already. "
                      "Message: %(err)s",
                      {'snap_name': snap.name,
                       'err': err})
        except storops_ex.UnityDeleteAttachedSnapError as err:
            with excutils.save_and_reraise_exception():
                LOG.warning("Failed to delete snapshot %(snap_name)s "
                            "which is in use. Message: %(err)s",
                            {'snap_name': snap.name, 'err': err})

    def get_snap(self, name=None):
        try:
            return self.system.get_snap(name=name)
        except storops_ex.UnityResourceNotFoundError as err:
            LOG.warning("Snapshot %(name)s doesn't exist. Message: %(err)s",
                        {'name': name, 'err': err})
        return None

    def lun_has_snapshot(self, lun):
        snaps = lun.snapshots
        return len(snaps) != 0

    @coordination.synchronized('{self.host}-{name}')
    def create_host(self, name):
        return self.create_host_wo_lock(name)

    def create_host_wo_lock(self, name):
        """Provides existing host if exists else create one."""
        if name not in self.host_cache:
            try:
                host = self.system.get_host(name=name)
            except storops_ex.UnityResourceNotFoundError:
                LOG.debug('Host %s not found.  Create a new one.',
                          name)
                host = self.system.create_host(name=name)

            self.host_cache[name] = host
        else:
            host = self.host_cache[name]
        return host

    def delete_host_wo_lock(self, host):
        host.delete()
        del self.host_cache[host.name]

    def update_host_initiators(self, host, uids):
        """Updates host with the supplied uids."""
        host_initiators_ids = self.get_host_initiator_ids(host)
        un_registered = [h for h in uids if h not in host_initiators_ids]
        if un_registered:
            for uid in un_registered:
                try:
                    host.add_initiator(uid, force_create=True)
                except storops_ex.UnityHostInitiatorExistedError:
                    # This make concurrent modification of
                    # host initiators safe
                    LOG.debug(
                        'The uid(%s) was already in '
                        '%s.', uid, host.name)
            host.update()
            # Update host cached with new initiators.
            self.host_cache[host.name] = host

        return host

    @staticmethod
    def get_host_initiator_ids(host):
        fc = host.fc_host_initiators
        fc_ids = [] if fc is None else fc.initiator_id
        iscsi = host.iscsi_host_initiators
        iscsi_ids = [] if iscsi is None else iscsi.initiator_id
        return fc_ids + iscsi_ids

    @staticmethod
    def attach(host, lun_or_snap):
        """Attaches a `UnityLun` or `UnitySnap` to a `UnityHost`.

        :param host: `UnityHost` object
        :param lun_or_snap: `UnityLun` or `UnitySnap` object
        :return: hlu
        """
        try:
            return host.attach(lun_or_snap, skip_hlu_0=True)
        except storops_ex.UnityResourceAlreadyAttachedError:
            return host.get_hlu(lun_or_snap)

    @staticmethod
    def detach(host, lun_or_snap):
        """Detaches a `UnityLun` or `UnitySnap` from a `UnityHost`.

        :param host: `UnityHost` object
        :param lun_or_snap: `UnityLun` object
        """
        lun_or_snap.update()
        host.detach(lun_or_snap)

    @staticmethod
    def detach_all(lun):
        """Detaches a `UnityLun` from all hosts.

        :param lun: `UnityLun` object
        """
        lun.update()
        lun.detach_from(host=None)

    def get_ethernet_ports(self):
        return self.system.get_ethernet_port()

    def get_iscsi_target_info(self, allowed_ports=None):
        portals = self.system.get_iscsi_portal()
        portals = portals.shadow_copy(port_ids=allowed_ports)
        return [{'portal': utils.convert_ip_to_portal(p.ip_address),
                 'iqn': p.iscsi_node.name}
                for p in portals]

    def get_fc_ports(self):
        return self.system.get_fc_port()

    def get_fc_target_info(self, host=None, logged_in_only=False,
                           allowed_ports=None):
        """Get the ports WWN of FC on array.

        :param host: the host to which the FC port is registered.
        :param logged_in_only: whether to retrieve only the logged-in port.

        :return: the WWN of FC ports. For example, the FC WWN on array is like:
         50:06:01:60:89:20:09:25:50:06:01:6C:09:20:09:25.
         This function removes the colons and returns the last 16 bits:
         5006016C09200925.
        """
        wwns = set()
        if logged_in_only:
            for paths in filter(None, host.fc_host_initiators.paths):
                paths = paths.shadow_copy(is_logged_in=True)
                # `paths.fc_port` is just a list, not a UnityFcPortList,
                # so use filter instead of shadow_copy here.
                wwns.update(p.wwn.upper()
                            for p in filter(
                    lambda fcp: (allowed_ports is None or
                                 fcp.get_id() in allowed_ports),
                    paths.fc_port))
        else:
            ports = self.get_fc_ports()
            ports = ports.shadow_copy(port_ids=allowed_ports)
            wwns.update(p.wwn.upper() for p in ports)
        return [wwn.replace(':', '')[16:] for wwn in wwns]

    def create_io_limit_policy(self, name, max_iops=None, max_kbps=None):
        try:
            limit = self.system.create_io_limit_policy(
                name, max_iops=max_iops, max_kbps=max_kbps)
        except storops_ex.UnityPolicyNameInUseError:
            limit = self.system.get_io_limit_policy(name=name)
        return limit

    def get_io_limit_policy(self, qos_specs):
        limit_policy = None
        if qos_specs is not None:
            limit_policy = self.create_io_limit_policy(
                qos_specs['id'],
                qos_specs.get(utils.QOS_MAX_IOPS),
                qos_specs.get(utils.QOS_MAX_BWS))
        return limit_policy

    def get_pool_id_by_name(self, name):
        pool = self.system.get_pool(name=name)
        return pool.get_id()

    def get_pool_name(self, lun_name):
        lun = self.system.get_lun(name=lun_name)
        return lun.pool_name

    def restore_snapshot(self, snap_name):
        snap = self.get_snap(snap_name)
        return snap.restore(delete_backup=True)

    def create_cg(self, name, description=None, lun_add=None):
        try:
            cg = self.system.create_cg(name, description=description,
                                       lun_add=lun_add)
        except storops_ex.UnityConsistencyGroupNameInUseError:
            LOG.debug('CG %s already exists. Return the existing one.', name)
            cg = self.system.get_cg(name=name)
        return cg

    def get_cg(self, name):
        try:
            cg = self.system.get_cg(name=name)
        except storops_ex.UnityResourceNotFoundError:
            LOG.info('CG %s not found.', name)
            return None
        else:
            return cg

    def delete_cg(self, name):
        cg = self.get_cg(name)
        if cg:
            cg.delete()  # Deleting cg will also delete the luns in it

    def update_cg(self, name, add_lun_ids, remove_lun_ids):
        cg = self.get_cg(name)
        cg.update_lun(add_luns=[self.get_lun(lun_id=lun_id)
                                for lun_id in add_lun_ids],
                      remove_luns=[self.get_lun(lun_id=lun_id)
                                   for lun_id in remove_lun_ids])

    def create_cg_snap(self, cg_name, snap_name=None):
        cg = self.get_cg(cg_name)
        # Creating snap of cg will create corresponding snaps of luns in it
        return cg.create_snap(name=snap_name, is_auto_delete=False)

    def filter_snaps_in_cg_snap(self, cg_snap_id):
        return self.system.get_snap(snap_group=cg_snap_id).list

    def create_cg_replication(self, cg_name, pool_id,
                              remote_system, max_time_out_of_sync):
        # Creates a new cg on remote system and sets up replication to it.
        src_cg = self.get_cg(cg_name)
        src_luns = src_cg.luns
        return src_cg.replicate_cg_with_dst_resource_provisioning(
            max_time_out_of_sync, src_luns, pool_id,
            dst_cg_name=cg_name, remote_system=remote_system)

    def is_cg_replicated(self, cg_name):
        src_cg = self.get_cg(cg_name)
        return src_cg.check_cg_is_replicated()

    def delete_cg_rep_session(self, cg_name):
        src_cg = self.get_cg(cg_name)
        rep_sessions = self.get_replication_session(src_resource_id=src_cg.id)
        for rep_session in rep_sessions:
            rep_session.delete()

    def failover_cg_rep_session(self, cg_name, sync):
        src_cg = self.get_cg(cg_name)
        rep_sessions = self.get_replication_session(src_resource_id=src_cg.id)
        for rep_session in rep_sessions:
            rep_session.failover(sync=sync)

    def failback_cg_rep_session(self, cg_name):
        cg = self.get_cg(cg_name)
        # failback starts from remote replication session
        rep_sessions = self.get_replication_session(dst_resource_id=cg.id)
        for rep_session in rep_sessions:
            rep_session.failback(force_full_copy=True)

    @staticmethod
    def create_replication(src_lun, max_time_out_of_sync,
                           dst_pool_id, remote_system):
        """Creates a new lun on remote system and sets up replication to it."""
        return src_lun.replicate_with_dst_resource_provisioning(
            max_time_out_of_sync, dst_pool_id, remote_system=remote_system,
            dst_lun_name=src_lun.name)

    def get_remote_system(self, name=None):
        """Gets remote system on the Unity system.

        :param name: remote system name.
        :return: remote system.
        """
        try:
            return self.system.get_remote_system(name=name)
        except storops_ex.UnityResourceNotFoundError:
            LOG.warning("Not found remote system with name %s. Return None.",
                        name)
            return None

    def get_replication_session(self, name=None,
                                src_resource_id=None, dst_resource_id=None):
        """Gets replication session via its name.

        :param name: replication session name.
        :param src_resource_id: replication session's src_resource_id.
        :param dst_resource_id: replication session's dst_resource_id.
        :return: replication session.
        """
        try:
            return self.system.get_replication_session(
                name=name, src_resource_id=src_resource_id,
                dst_resource_id=dst_resource_id)
        except storops_ex.UnityResourceNotFoundError:
            raise ClientReplicationError(
                'Replication session with name %(name)s not found.' %
                {'name': name})

    def failover_replication(self, rep_session):
        """Fails over a replication session.

        :param rep_session: replication session to fail over.
        """
        name = rep_session.name
        LOG.debug('Failing over replication: %s', name)
        try:
            # In OpenStack, only support to failover triggered from secondary
            # backend because the primary could be down. Then `sync=False`
            # is required here which means it won't sync from primary to
            # secondary before failover.
            return rep_session.failover(sync=False)
        except storops_ex.UnityException as ex:
            raise ClientReplicationError(
                'Failover of replication: %(name)s failed, '
                'error: %(err)s' % {'name': name, 'err': ex}
            )
        LOG.debug('Replication: %s failed over', name)

    def failback_replication(self, rep_session):
        """Fails back a replication session.

        :param rep_session: replication session to fail back.
        """
        name = rep_session.name
        LOG.debug('Failing back replication: %s', name)
        try:
            # If the replication was failed-over before initial copy done,
            # following failback will fail without `force_full_copy` because
            # the primary # and secondary data have no common base.
            # `force_full_copy=True` has no effect if initial copy done.
            return rep_session.failback(force_full_copy=True)
        except storops_ex.UnityException as ex:
            raise ClientReplicationError(
                'Failback of replication: %(name)s failed, '
                'error: %(err)s' % {'name': name, 'err': ex}
            )
        LOG.debug('Replication: %s failed back', name)


class ClientReplicationError(exception.CinderException):
    pass
