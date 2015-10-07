# Copyright 2014 Violin Memory, Inc.
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
Violin Memory Fibre Channel Driver for Openstack Cinder

Provides fibre channel specific LUN services for V6000 series flash
arrays.

This driver requires VMOS v6.3.0.4 or newer software on the array.

You will need to install the Violin Memory REST client library:
sudo pip install vmemclient

Set the following in the cinder.conf file to enable the VMEM V6000
Fibre Channel Driver along with the required flags:

volume_driver=cinder.volume.drivers.violin.v6000_fcp.V6000FCDriver

NOTE: this driver file requires the use of synchronization points for
certain types of backend operations, and as a result may not work
properly in an active-active HA configuration.  See OpenStack Cinder
driver documentation for more information.
"""

from oslo_log import log as logging
from oslo_utils import units
from six.moves import range

from cinder import context
from cinder.db.sqlalchemy import models
from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume.drivers.violin import v6000_common
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


class V6000FCDriver(driver.FibreChannelDriver):
    """Executes commands relating to fibre channel based Violin Memory Arrays.

    Version history:
        1.0 - Initial driver
        1.0.1 - Fixes polling for export completion
    """

    VERSION = '1.0.1'

    def __init__(self, *args, **kwargs):
        super(V6000FCDriver, self).__init__(*args, **kwargs)
        self.gateway_fc_wwns = []
        self.stats = {}
        self.configuration.append_config_values(v6000_common.violin_opts)
        self.configuration.append_config_values(san.san_opts)
        self.common = v6000_common.V6000Common(self.configuration)
        self.lookup_service = fczm_utils.create_lookup_service()

        LOG.info(_LI("Initialized driver %(name)s version: %(vers)s."),
                 {'name': self.__class__.__name__, 'vers': self.VERSION})

    def do_setup(self, context):
        """Any initialization the driver does while starting."""
        super(V6000FCDriver, self).do_setup(context)
        self.common.do_setup(context)
        self.gateway_fc_wwns = self._get_active_fc_targets()

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        self.common.check_for_setup_error()

        if len(self.gateway_fc_wwns) == 0:
            raise exception.ViolinInvalidBackendConfig(
                reason=_('No FCP targets found'))

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

    @fczm_utils.AddFCZone
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

        if isinstance(volume, models.Volume):
            lun_id = self._export_lun(volume, connector, igroup)
        else:
            lun_id = self._export_snapshot(volume, connector, igroup)
        self.common.vip.basic.save_config()

        target_wwns, init_targ_map = self._build_initiator_target_map(
            connector)

        properties = {}
        properties['target_discovered'] = True
        properties['target_wwn'] = target_wwns
        properties['target_lun'] = lun_id
        properties['initiator_target_map'] = init_targ_map

        LOG.debug("Return FC data for zone addition: %(properties)s.",
                  {'properties': properties})

        return {'driver_volume_type': 'fibre_channel', 'data': properties}

    @fczm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, force=False, **kwargs):
        """Terminates the connection (target<-->initiator)."""

        if isinstance(volume, models.Volume):
            self._unexport_lun(volume)
        else:
            self._unexport_snapshot(volume)

        self.common.vip.basic.save_config()

        properties = {}

        if not self._is_initiator_connected_to_array(connector):
            target_wwns, init_targ_map = self._build_initiator_target_map(
                connector)
            properties['target_wwn'] = target_wwns
            properties['initiator_target_map'] = init_targ_map

        LOG.debug("Return FC data for zone deletion: %(properties)s.",
                  {'properties': properties})

        return {'driver_volume_type': 'fibre_channel', 'data': properties}

    def get_volume_stats(self, refresh=False):
        """Get volume stats."""
        if refresh or not self.stats:
            self._update_stats()
        return self.stats

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
            export_to = self._convert_wwns_openstack_to_vmem(
                connector['wwpns'])
        else:
            raise exception.Error(_("No initiators found, cannot proceed"))

        LOG.debug("Exporting lun %s.", volume['id'])

        try:
            self.common._send_cmd_and_verify(
                v.lun.export_lun, self.common._wait_for_export_state, '',
                [self.common.container, volume['id'], 'all', export_to,
                 'auto'], [volume['id'], None, True])

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

        if igroup:
            export_to = igroup
        elif connector:
            export_to = self._convert_wwns_openstack_to_vmem(
                connector['wwpns'])
        else:
            raise exception.Error(_("No initiators found, cannot proceed"))

        LOG.debug("Exporting snapshot %s.", snapshot['id'])

        try:
            self.common._send_cmd(v.snapshot.export_lun_snapshot, '',
                                  self.common.container, snapshot['volume_id'],
                                  snapshot['id'], export_to, 'all', 'auto')

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
        """Add an initiator to the openstack igroup so it can see exports.

        The equivalent CLI command is "igroup addto name <igroup_name>
        initiators <initiator_name>"

        Arguments:
            connector -- connector object provided by the Manager
        """
        v = self.common.vip
        wwpns = self._convert_wwns_openstack_to_vmem(connector['wwpns'])

        LOG.debug("Adding initiators %(wwpns)s to igroup %(igroup)s.",
                  {'wwpns': wwpns, 'igroup': igroup})

        resp = v.igroup.add_initiators(igroup, wwpns)

        if resp['code'] != 0:
            raise exception.Error(
                _('Failed to add igroup member: %(code)d, %(message)s') % resp)

    def _build_initiator_target_map(self, connector):
        """Build the target_wwns and the initiator target map."""
        target_wwns = []
        init_targ_map = {}

        if self.lookup_service:
            dev_map = self.lookup_service.get_device_mapping_from_network(
                connector['wwpns'], self.gateway_fc_wwns)

            for fabric_name in dev_map:
                fabric = dev_map[fabric_name]
                target_wwns += fabric['target_port_wwn_list']
                for initiator in fabric['initiator_port_wwn_list']:
                    if initiator not in init_targ_map:
                        init_targ_map[initiator] = []
                    init_targ_map[initiator] += fabric['target_port_wwn_list']
                    init_targ_map[initiator] = list(
                        set(init_targ_map[initiator]))

            target_wwns = list(set(target_wwns))

        else:
            initiator_wwns = connector['wwpns']
            target_wwns = self.gateway_fc_wwns
            for initiator in initiator_wwns:
                init_targ_map[initiator] = target_wwns

        return target_wwns, init_targ_map

    def _is_initiator_connected_to_array(self, connector):
        """Check array to see if any initiator wwns still have active sessions.

        We only need to check to see if any one initiator wwn is
        connected, since all initiators are connected to all targets
        on a lun export for fibrechannel.
        """
        v = self.common.vip
        initiator_wwns = self._convert_wwns_openstack_to_vmem(
            connector['wwpns'])

        bn = "/vshare/config/export/container/%s/lun/**" \
            % self.common.container
        global_export_config = v.basic.get_node_values(bn)

        for node in global_export_config:
            if node.endswith(initiator_wwns[0]):
                return True
        return False

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
        data['storage_protocol'] = 'fibre_channel'
        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        data['total_capacity_gb'] = total_gb
        data['free_capacity_gb'] = free_gb

        for i in data:
            LOG.debug("stat update: %(name)s=%(data)s.",
                      {'name': i, 'data': data[i]})
        self.stats = data

    def _get_active_fc_targets(self):
        """Get a list of gateway WWNs that can be used as FCP targets.

        Arguments:
            mg_conn -- active XG connection to one of the gateways

        Returns:
            active_gw_fcp_wwns -- list of WWNs
        """
        v = self.common.vip
        active_gw_fcp_wwns = []

        gateway_ids = v.basic.get_node_values(
            '/vshare/state/global/*').values()

        for i in gateway_ids:
            bn = "/vshare/state/global/%d/target/fc/**" % i
            resp = v.basic.get_node_values(bn)

            for node in resp:
                if node.endswith('/wwn'):
                    active_gw_fcp_wwns.append(resp[node])

        return self._convert_wwns_vmem_to_openstack(active_gw_fcp_wwns)

    def _convert_wwns_openstack_to_vmem(self, wwns):
        """Convert a list of Openstack WWNs to VMEM compatible WWN strings.

        Input format is '50014380186b3f65', output format is
        'wwn.50:01:43:80:18:6b:3f:65'.

        Arguments:
            wwns -- list of Openstack-based WWN strings.

        Returns:
            output -- list of VMEM-based WWN strings.
        """
        output = []
        for w in wwns:
            output.append('wwn.{0}'.format(
                ':'.join(w[x:x + 2] for x in range(0, len(w), 2))))
        return output

    def _convert_wwns_vmem_to_openstack(self, wwns):
        """Convert a list of VMEM WWNs to Openstack compatible WWN strings.

        Input format is 'wwn.50:01:43:80:18:6b:3f:65', output format
        is '50014380186b3f65'.

        Arguments:
            wwns -- list of VMEM-based WWN strings.

        Returns:
            output -- list of Openstack-based WWN strings.
        """
        output = []
        for w in wwns:
            output.append(''.join(w[4:].split(':')))
        return output
