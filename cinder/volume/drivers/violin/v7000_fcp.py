# Copyright 2015 Violin Memory, Inc.
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
Violin 7000 Series All-Flash Array Volume Driver

Provides fibre channel specific LUN services for V7000 series flash
arrays.

This driver requires Concerto v7.0.0 or newer software on the array.

You will need to install the Violin Memory REST client library:
sudo pip install vmemclient

Set the following in the cinder.conf file to enable the VMEM V7000
Fibre Channel Driver along with the required flags:

volume_driver=cinder.volume.drivers.violin.v7000_fcp.V7000FCDriver

NOTE: this driver file requires the use of synchronization points for
certain types of backend operations, and as a result may not work
properly in an active-active HA configuration.  See OpenStack Cinder
driver documentation for more information.
"""

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume.drivers.violin import v7000_common
from cinder.zonemanager import utils as fczm_utils

import socket

LOG = logging.getLogger(__name__)


@interface.volumedriver
class V7000FCPDriver(driver.FibreChannelDriver):
    """Executes commands relating to fibre channel based Violin Memory arrays.

    Version history:
        1.0 - Initial driver
    """

    VERSION = '1.0'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Violin_Memory_CI"

    # TODO(smcginnis) Either remove this if CI requirements are met, or
    # remove this driver in the Queens release per normal deprecation
    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        super(V7000FCPDriver, self).__init__(*args, **kwargs)
        self.gateway_fc_wwns = []
        self.stats = {}
        self.configuration.append_config_values(v7000_common.violin_opts)
        self.configuration.append_config_values(san.san_opts)
        self.common = v7000_common.V7000Common(self.configuration)
        self.lookup_service = fczm_utils.create_lookup_service()

        LOG.info("Initialized driver %(name)s version: %(vers)s",
                 {'name': self.__class__.__name__, 'vers': self.VERSION})

    def do_setup(self, context):
        """Any initialization the driver does while starting."""
        super(V7000FCPDriver, self).do_setup(context)

        self.common.do_setup(context)
        self.gateway_fc_wwns = self._get_active_fc_targets()

        # Register the client with the storage array
        fc_version = self.VERSION + "-FCP"
        self.common.vmem_mg.utility.set_managed_by_openstack_version(
            fc_version)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        self.common.check_for_setup_error()
        if len(self.gateway_fc_wwns) == 0:
            raise exception.ViolinInvalidBackendConfig(
                reason=_('No FCP targets found'))

    def create_volume(self, volume):
        """Creates a volume."""
        self.common._create_lun(volume)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self.common._create_volume_from_snapshot(snapshot, volume)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        self.common._create_lun_from_lun(src_vref, volume)

    def delete_volume(self, volume):
        """Deletes a volume."""
        self.common._delete_lun(volume)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume's size."""
        self.common._extend_lun(volume, new_size)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self.common._create_lun_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self.common._delete_lun_snapshot(snapshot)

    def ensure_export(self, context, volume):
        """Synchronously checks and re-exports volumes at cinder start time."""
        pass

    def create_export(self, context, volume, connector):
        """Exports the volume."""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass

    @fczm_utils.add_fc_zone
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""

        LOG.debug("Initialize_connection: initiator - %(initiator)s  host - "
                  "%(host)s wwpns - %(wwpns)s",
                  {'initiator': connector['initiator'],
                   'host': connector['host'],
                   'wwpns': connector['wwpns']})

        self.common.vmem_mg.client.create_client(
            name=connector['host'], proto='FC', fc_wwns=connector['wwpns'])

        lun_id = self._export_lun(volume, connector)

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

    @fczm_utils.remove_fc_zone
    def terminate_connection(self, volume, connector, **kwargs):
        """Terminates the connection (target<-->initiator)."""

        self._unexport_lun(volume, connector)

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
        """Get volume stats.

        If 'refresh' is True, update the stats first.
        """
        if refresh or not self.stats:
            self._update_volume_stats()
        return self.stats

    @utils.synchronized('vmem-export')
    def _export_lun(self, volume, connector=None):
        """Generates the export configuration for the given volume.

        :param volume:  volume object provided by the Manager
        :param connector:  connector object provided by the Manager
        :returns: the LUN ID assigned by the backend
        """
        lun_id = ''
        v = self.common.vmem_mg

        if not connector:
            raise exception.ViolinInvalidBackendConfig(
                reason=_('No initiators found, cannot proceed'))

        LOG.debug("Exporting lun %(vol_id)s - initiator wwpns %(i_wwpns)s "
                  "- target wwpns %(t_wwpns)s.",
                  {'vol_id': volume['id'], 'i_wwpns': connector['wwpns'],
                   't_wwpns': self.gateway_fc_wwns})

        try:
            lun_id = self.common._send_cmd_and_verify(
                v.lun.assign_lun_to_client,
                self._is_lun_id_ready,
                "Assign SAN client successfully",
                [volume['id'], connector['host'],
                 "ReadWrite"],
                [volume['id'], connector['host']])

        except exception.ViolinBackendErr:
            LOG.exception("Backend returned err for lun export.")
            raise

        except Exception:
            raise exception.ViolinInvalidBackendConfig(
                reason=_('LUN export failed!'))

        lun_id = self._get_lun_id(volume['id'], connector['host'])
        LOG.info("Exported lun %(vol_id)s on lun_id %(lun_id)s.",
                 {'vol_id': volume['id'], 'lun_id': lun_id})

        return lun_id

    @utils.synchronized('vmem-export')
    def _unexport_lun(self, volume, connector=None):
        """Removes the export configuration for the given volume.

        :param volume:  volume object provided by the Manager
        """
        v = self.common.vmem_mg

        LOG.info("Unexporting lun %s.", volume['id'])

        try:
            self.common._send_cmd(v.lun.unassign_client_lun,
                                  "Unassign SAN client successfully",
                                  volume['id'], connector['host'], True)

        except exception.ViolinBackendErr:
            LOG.exception("Backend returned err for lun export.")
            raise

        except Exception:
            LOG.exception("LUN unexport failed!")
            raise

    def _update_volume_stats(self):
        """Gathers array stats and converts them to GB values."""
        data = {}
        total_gb = 0
        free_gb = 0
        v = self.common.vmem_mg.basic
        array_name_triple = socket.gethostbyaddr(self.configuration.san_ip)
        array_name = array_name_triple[0]

        phy_devices = v.get("/batch/physicalresource/physicaldevice")

        all_devices = [x for x in phy_devices['data']['physical_devices']]

        for x in all_devices:
            if socket.getfqdn(x['owner']) == array_name:
                total_gb += x['size_mb'] // 1024
                free_gb += x['availsize_mb'] // 1024

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
            LOG.debug("stat update: %(name)s=%(data)s",
                      {'name': i, 'data': data[i]})

        self.stats = data

    def _get_active_fc_targets(self):
        """Get a list of gateway WWNs that can be used as FCP targets.

        :param mg_conn:  active XG connection to one of the gateways
        :returns:  list of WWNs in openstack format
        """
        v = self.common.vmem_mg
        active_gw_fcp_wwns = []

        fc_info = v.adapter.get_fc_info()
        for x in fc_info.values():
            active_gw_fcp_wwns.append(x[0])

        return active_gw_fcp_wwns

    def _get_lun_id(self, volume_name, client_name):
        """Get the lun ID for an exported volume.

        If the lun is successfully assigned (exported) to a client, the
        client info has the lun_id.

        :param volume_name:  name of volume to query for lun ID
        :param client_name:  name of client associated with the volume
        :returns: integer value of lun ID
        """
        v = self.common.vmem_mg
        lun_id = None

        client_info = v.client.get_client_info(client_name)

        for x in client_info['FibreChannelDevices']:
            if volume_name == x['name']:
                lun_id = x['lun']
                break

        if lun_id:
            lun_id = int(lun_id)

        return lun_id

    def _is_lun_id_ready(self, volume_name, client_name):
        """Get the lun ID for an exported volume.

        If the lun is successfully assigned (exported) to a client, the
        client info has the lun_id.

        :param volume_name:  name of volume to query for lun ID
        :param client_name:  name of client associated with the volume
        :returns: Returns True if lun is ready, False otherwise
        """

        lun_id = -1
        lun_id = self._get_lun_id(volume_name, client_name)
        if lun_id is None:
            return False
        else:
            return True

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
        """Check if any initiator wwns still have active sessions."""
        v = self.common.vmem_mg

        client = v.client.get_client_info(connector['host'])

        if len(client['FibreChannelDevices']):
            # each entry in the FibreChannelDevices array is a dict
            # describing an active lun assignment
            return True
        return False
