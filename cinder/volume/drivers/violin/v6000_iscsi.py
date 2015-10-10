# Copyright 2013 Violin Memory, Inc.
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

"""
Violin Memory iSCSI Driver for Openstack Cinder

Provides iSCSI specific LUN services for V6000 series flash arrays.

This driver requires VMOS v6.3.0.4 or newer software on the array.

You will need to install the Violin Memory REST client library:
sudo pip install vmemclient

Set the following in the cinder.conf file to enable the VMEM V6000
ISCSI Driver along with the required flags:

volume_driver=cinder.volume.drivers.violin.v6000_iscsi.V6000ISCSIDriver

NOTE: this driver file requires the use of synchronization points for
certain types of backend operations, and as a result may not work
properly in an active-active HA configuration.  See OpenStack Cinder
driver documentation for more information.
"""

import random

from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import units

from cinder import context
from cinder.db.sqlalchemy import models
from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume.drivers.violin import v6000_common

LOG = logging.getLogger(__name__)


class V6000ISCSIDriver(driver.ISCSIDriver):
    """Executes commands relating to iSCSI-based Violin Memory Arrays.

    Version history:
        1.0 - Initial driver
        1.0.1 - Fixes polling for export completion
    """

    VERSION = '1.0.1'
    TARGET_GROUP_NAME = 'openstack'

    def __init__(self, *args, **kwargs):
        super(V6000ISCSIDriver, self).__init__(*args, **kwargs)
        self.array_info = []
        self.gateway_iscsi_ip_addresses_mga = []
        self.gateway_iscsi_ip_addresses_mgb = []
        self.stats = {}
        self.configuration.append_config_values(v6000_common.violin_opts)
        self.configuration.append_config_values(san.san_opts)
        self.common = v6000_common.V6000Common(self.configuration)

        LOG.info(_LI("Initialized driver %(name)s version: %(vers)s."),
                 {'name': self.__class__.__name__, 'vers': self.VERSION})

    def do_setup(self, context):
        """Any initialization the driver does while starting."""
        super(V6000ISCSIDriver, self).do_setup(context)
        self.common.do_setup(context)

        self.gateway_iscsi_ip_addresses_mga = self._get_active_iscsi_ips(
            self.common.mga)
        for ip in self.gateway_iscsi_ip_addresses_mga:
            self.array_info.append({"node": self._get_hostname('mga'),
                                    "addr": ip,
                                    "conn": self.common.mga})
        self.gateway_iscsi_ip_addresses_mgb = self._get_active_iscsi_ips(
            self.common.mgb)
        for ip in self.gateway_iscsi_ip_addresses_mgb:
            self.array_info.append({"node": self._get_hostname('mgb'),
                                    "addr": ip,
                                    "conn": self.common.mgb})

        # setup global target group for exports to use
        self._create_iscsi_target_group()

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        self.common.check_for_setup_error()

        bn = "/vshare/config/iscsi/enable"
        resp = self.common.vip.basic.get_node_values(bn)
        if resp[bn] is not True:
            raise exception.ViolinInvalidBackendConfig(
                reason=_('iSCSI is not enabled'))
        if len(self.gateway_iscsi_ip_addresses_mga) == 0:
            raise exception.ViolinInvalidBackendConfig(
                reason=_('no available iSCSI IPs on mga'))
        if len(self.gateway_iscsi_ip_addresses_mgb) == 0:
            raise exception.ViolinInvalidBackendConfig(
                reason=_('no available iSCSI IPs on mgb'))

    def create_volume(self, volume):
        """Creates a volume."""
        self.common._create_lun(volume)

    def delete_volume(self, volume):
        """Deletes a volume."""
        self.common._delete_lun(volume)

    def extend_volume(self, volume, new_size):
        """Deletes a volume."""
        self.common._extend_lun(volume, new_size)

    def create_snapshot(self, snapshot):
        """Creates a snapshot from an existing volume."""
        self.common._create_lun_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self.common._delete_lun_snapshot(snapshot)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        ctxt = context.get_admin_context()
        snapshot['size'] = snapshot['volume']['size']
        self.common._create_lun(volume)
        self.copy_volume_data(ctxt, snapshot, volume)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a full clone of the specified volume."""
        ctxt = context.get_admin_context()
        self.common._create_lun(volume)
        self.copy_volume_data(ctxt, src_vref, volume)

    def ensure_export(self, context, volume):
        """Synchronously checks and re-exports volumes at cinder start time."""
        pass

    def create_export(self, context, volume, connector):
        """Exports the volume."""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass

    def initialize_connection(self, volume, connector):
        """Initializes the connection (target<-->initiator)."""
        igroup = None

        if self.configuration.use_igroups:
            #
            # Most drivers don't use igroups, because there are a
            # number of issues with multipathing and iscsi/fcp where
            # lun devices either aren't cleaned up properly or are
            # stale (from previous scans).
            #

            # If the customer really wants igroups for whatever
            # reason, we create a new igroup for each host/hypervisor.
            # Every lun that is exported to the particular
            # hypervisor/host will be contained in this igroup.  This
            # should prevent other hosts from seeing luns they aren't
            # using when they perform scans.
            #
            igroup = self.common._get_igroup(volume, connector)
            self._add_igroup_member(connector, igroup)

        tgt = self._get_iscsi_target()
        target_name = self.TARGET_GROUP_NAME

        if isinstance(volume, models.Volume):
            lun = self._export_lun(volume, connector, igroup)
        else:
            lun = self._export_snapshot(volume, connector, igroup)

        iqn = "%s%s:%s" % (self.configuration.iscsi_target_prefix,
                           tgt['node'], target_name)
        self.common.vip.basic.save_config()

        properties = {}
        properties['target_discovered'] = False
        properties['target_portal'] = '%s:%d' \
            % (tgt['addr'], self.configuration.iscsi_port)
        properties['target_iqn'] = iqn
        properties['target_lun'] = lun
        properties['volume_id'] = volume['id']
        properties['auth_method'] = 'CHAP'
        properties['auth_username'] = ''
        properties['auth_password'] = ''

        return {'driver_volume_type': 'iscsi', 'data': properties}

    def terminate_connection(self, volume, connector, force=False, **kwargs):
        """Terminates the connection (target<-->initiator)."""
        if isinstance(volume, models.Volume):
            self._unexport_lun(volume)
        else:
            self._unexport_snapshot(volume)
        self.common.vip.basic.save_config()

    def get_volume_stats(self, refresh=False):
        """Get volume stats."""
        if refresh or not self.stats:
            self._update_stats()
        return self.stats

    def _create_iscsi_target_group(self):
        """Creates a new target for use in exporting a lun.

        Create an HA target on the backend that will be used for all
        lun exports made via this driver.

        The equivalent CLI commands are "iscsi target create
        <target_name>" and "iscsi target bind <target_name> to
        <ip_of_mg_eth_intf>".
        """
        v = self.common.vip
        target_name = self.TARGET_GROUP_NAME

        bn = "/vshare/config/iscsi/target/%s" % target_name
        resp = self.common.vip.basic.get_node_values(bn)

        if resp:
            LOG.debug("iscsi target group %s already exists.", target_name)
            return

        LOG.debug("Creating iscsi target %s.", target_name)

        try:
            self.common._send_cmd_and_verify(v.iscsi.create_iscsi_target,
                                             self._wait_for_target_state,
                                             '', [target_name], [target_name])

        except Exception:
            LOG.exception(_LE("Failed to create iscsi target!"))
            raise

        try:
            self.common._send_cmd(self.common.mga.iscsi.bind_ip_to_target,
                                  '', target_name,
                                  self.gateway_iscsi_ip_addresses_mga)
            self.common._send_cmd(self.common.mgb.iscsi.bind_ip_to_target,
                                  '', target_name,
                                  self.gateway_iscsi_ip_addresses_mgb)

        except Exception:
            LOG.exception(_LE("Failed to bind iSCSI targets!"))
            raise

    def _get_iscsi_target(self):
        """Get a random target IP for OpenStack to connect to.

        For the non-multipath case we pick a single random target for
        the Openstack infrastructure to use.  This at least allows us
        to evenly distribute LUN connections across the storage
        cluster.
        """
        return self.array_info[random.randint(0, len(self.array_info) - 1)]

    @utils.synchronized('vmem-export')
    def _export_lun(self, volume, connector=None, igroup=None):
        """Generates the export configuration for the given volume.

        The equivalent CLI command is "lun export container
        <container_name> name <lun_name>"

        Arguments:
            volume -- volume object provided by the Manager
            connector -- connector object provided by the Manager
            igroup -- name of igroup to use for exporting

        Returns:
            lun_id -- the LUN ID assigned by the backend
        """
        lun_id = -1
        export_to = ''
        v = self.common.vip

        if igroup:
            export_to = igroup
        elif connector:
            export_to = connector['initiator']
        else:
            raise exception.Error(_("No initiators found, cannot proceed"))

        target_name = self.TARGET_GROUP_NAME

        LOG.debug("Exporting lun %s.", volume['id'])

        try:
            self.common._send_cmd_and_verify(
                v.lun.export_lun, self.common._wait_for_export_state, '',
                [self.common.container, volume['id'], target_name,
                 export_to, 'auto'], [volume['id'], None, True])

        except Exception:
            LOG.exception(_LE("LUN export for %s failed!"), volume['id'])
            raise

        lun_id = self.common._get_lun_id(volume['id'])

        return lun_id

    @utils.synchronized('vmem-export')
    def _unexport_lun(self, volume):
        """Removes the export configuration for the given volume.

        The equivalent CLI command is "no lun export container
        <container_name> name <lun_name>"

        Arguments:
            volume -- volume object provided by the Manager
        """
        v = self.common.vip

        LOG.debug("Unexporting lun %s.", volume['id'])

        try:
            self.common._send_cmd_and_verify(
                v.lun.unexport_lun, self.common._wait_for_export_state, '',
                [self.common.container, volume['id'], 'all', 'all', 'auto'],
                [volume['id'], None, False])

        except exception.ViolinBackendErrNotFound:
            LOG.debug("Lun %s already unexported, continuing.", volume['id'])

        except Exception:
            LOG.exception(_LE("LUN unexport for %s failed!"), volume['id'])
            raise

    @utils.synchronized('vmem-export')
    def _export_snapshot(self, snapshot, connector=None, igroup=None):
        """Generates the export configuration for the given snapshot.

        The equivalent CLI command is "snapshot export container
        PROD08 lun <snapshot_name> name <volume_name>"

        Arguments:
            snapshot -- snapshot object provided by the Manager
            connector -- connector object provided by the Manager
            igroup -- name of igroup to use for exporting

        Returns:
            lun_id -- the LUN ID assigned by the backend
        """
        lun_id = -1
        export_to = ''
        v = self.common.vip

        target_name = self.TARGET_GROUP_NAME

        LOG.debug("Exporting snapshot %s.", snapshot['id'])

        if igroup:
            export_to = igroup
        elif connector:
            export_to = connector['initiator']
        else:
            raise exception.Error(_("No initiators found, cannot proceed"))

        try:
            self.common._send_cmd(v.snapshot.export_lun_snapshot, '',
                                  self.common.container, snapshot['volume_id'],
                                  snapshot['id'], export_to, target_name,
                                  'auto')

        except Exception:
            LOG.exception(_LE("Snapshot export for %s failed!"),
                          snapshot['id'])
            raise

        else:
            self.common._wait_for_export_state(snapshot['volume_id'],
                                               snapshot['id'], state=True)
            lun_id = self.common._get_snapshot_id(snapshot['volume_id'],
                                                  snapshot['id'])

        return lun_id

    @utils.synchronized('vmem-export')
    def _unexport_snapshot(self, snapshot):
        """Removes the export configuration for the given snapshot.

        The equivalent CLI command is "no snapshot export container
        PROD08 lun <snapshot_name> name <volume_name>"

        Arguments:
            snapshot -- snapshot object provided by the Manager
        """
        v = self.common.vip

        LOG.debug("Unexporting snapshot %s.", snapshot['id'])

        try:
            self.common._send_cmd(v.snapshot.unexport_lun_snapshot, '',
                                  self.common.container, snapshot['volume_id'],
                                  snapshot['id'], 'all', 'all', 'auto', False)

        except Exception:
            LOG.exception(_LE("Snapshot unexport for %s failed!"),
                          snapshot['id'])
            raise

        else:
            self.common._wait_for_export_state(snapshot['volume_id'],
                                               snapshot['id'], state=False)

    def _add_igroup_member(self, connector, igroup):
        """Add an initiator to an igroup so it can see exports.

        The equivalent CLI command is "igroup addto name <igroup_name>
        initiators <initiator_name>"

        Arguments:
            connector -- connector object provided by the Manager
        """
        v = self.common.vip

        LOG.debug("Adding initiator %s to igroup.", connector['initiator'])

        resp = v.igroup.add_initiators(igroup, connector['initiator'])

        if resp['code'] != 0:
            raise exception.Error(
                _('Failed to add igroup member: %(code)d, %(message)s') % resp)

    def _update_stats(self):
        """Update array stats.

        Gathers array stats from the backend and converts them to GB values.
        """
        data = {}
        total_gb = 0
        free_gb = 0
        v = self.common.vip

        master_cluster_id = list(v.basic.get_node_values(
            '/cluster/state/master_id').values())[0]

        bn1 = "/vshare/state/global/%s/container/%s/total_bytes" \
            % (master_cluster_id, self.common.container)
        bn2 = "/vshare/state/global/%s/container/%s/free_bytes" \
            % (master_cluster_id, self.common.container)
        resp = v.basic.get_node_values([bn1, bn2])

        if bn1 in resp:
            total_gb = resp[bn1] // units.Gi
        else:
            LOG.warning(_LW("Failed to receive update for total_gb stat!"))
            if 'total_capacity_gb' in self.stats:
                total_gb = self.stats['total_capacity_gb']

        if bn2 in resp:
            free_gb = resp[bn2] // units.Gi
        else:
            LOG.warning(_LW("Failed to receive update for free_gb stat!"))
            if 'free_capacity_gb' in self.stats:
                free_gb = self.stats['free_capacity_gb']

        backend_name = self.configuration.volume_backend_name
        data['volume_backend_name'] = backend_name or self.__class__.__name__
        data['vendor_name'] = 'Violin Memory, Inc.'
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = 'iSCSI'
        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        data['total_capacity_gb'] = total_gb
        data['free_capacity_gb'] = free_gb

        for i in data:
            LOG.debug("stat update: %(name)s=%(data)s.",
                      {'name': i, 'data': data[i]})

        self.stats = data

    def _get_short_name(self, volume_name):
        """Creates a vSHARE-compatible iSCSI target name.

        The Folsom-style volume names are prefix(7) + uuid(36), which
        is too long for vSHARE for target names.  To keep things
        simple we can just truncate the name to 32 chars.

        Arguments:
            volume_name -- name of volume/lun

        Returns:
            Shortened volume name as a string.
        """
        return volume_name[:32]

    def _get_active_iscsi_ips(self, mg_conn):
        """Get a list of gateway IP addresses that can be used for iSCSI.

        Arguments:
            mg_conn -- active XG connection to one of the gateways

        Returns:
            active_gw_iscsi_ips -- list of IP addresses
        """
        active_gw_iscsi_ips = []
        interfaces_to_skip = ['lo', 'vlan10', 'eth1', 'eth2', 'eth3']

        bn = "/net/interface/config/*"
        intf_list = mg_conn.basic.get_node_values(bn)

        for i in intf_list:
            if intf_list[i] in interfaces_to_skip:
                continue

            bn1 = "/net/interface/state/%s/addr/ipv4/1/ip" % intf_list[i]
            bn2 = "/net/interface/state/%s/flags/link_up" % intf_list[i]
            resp = mg_conn.basic.get_node_values([bn1, bn2])

            if len(resp.keys()) == 2 and resp[bn2] is True:
                active_gw_iscsi_ips.append(resp[bn1])

        return active_gw_iscsi_ips

    def _get_hostname(self, mg_to_query=None):
        """Get the hostname of one of the mgs (hostname is used in IQN).

        If the remote query fails then fall back to using the hostname
        provided in the cinder configuration file.

        Arguments:
            mg_to_query -- name of gateway to query 'mga' or 'mgb'

        Returns: hostname -- hostname as a string
        """
        hostname = self.configuration.san_ip
        conn = self.common.vip

        if mg_to_query == "mga":
            hostname = self.configuration.gateway_mga
            conn = self.common.mga
        elif mg_to_query == "mgb":
            hostname = self.configuration.gateway_mgb
            conn = self.common.mgb

        ret_dict = conn.basic.get_node_values("/system/hostname")
        if ret_dict:
            hostname = list(ret_dict.items())[0][1]
        else:
            LOG.debug("Unable to fetch gateway hostname for %s.", mg_to_query)

        return hostname

    def _wait_for_target_state(self, target_name):
        """Polls backend to verify an iscsi target configuration.

        This function will try to verify the creation of an iscsi
        target on both gateway nodes of the array every 5 seconds.

        Arguments:
            target_name -- name of iscsi target to be polled

        Returns:
            True if the target state was correctly added
        """
        bn = "/vshare/state/local/target/iscsi/%s" % (target_name)

        def _loop_func():
            status = [False, False]
            mg_conns = [self.common.mga, self.common.mgb]

            LOG.debug("Entering _wait_for_target_state loop: target=%s.",
                      target_name)

            for node_id in range(2):
                resp = mg_conns[node_id].basic.get_node_values(bn)
                if len(resp.keys()):
                    status[node_id] = True

            if status[0] and status[1]:
                raise loopingcall.LoopingCallDone(retvalue=True)

        timer = loopingcall.FixedIntervalLoopingCall(_loop_func)
        success = timer.start(interval=5).wait()

        return success
