# Copyright (c) 2014 FUJITSU LIMITED
# Copyright (c) 2014 EMC Corporation.
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
FC Drivers for ETERNUS DX arrays based on SMI-S.

"""
import six

from cinder import context
from cinder.openstack.common import lockutils
from cinder.openstack.common import log as logging
from cinder.volume import driver
from cinder.volume.drivers import fujitsu_eternus_dx_common
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


class FJDXFCDriver(driver.FibreChannelDriver):
    """FC Drivers using SMI-S."""

    VERSION = "1.2.0"

    def __init__(self, *args, **kwargs):

        super(FJDXFCDriver, self).__init__(*args, **kwargs)
        self.common = fujitsu_eternus_dx_common.FJDXCommon(
            'FC',
            configuration=self.configuration)

    def check_for_setup_error(self):
        pass

    @lockutils.synchronized('ETERNUS_DX-vol', 'cinder-', True)
    def create_volume(self, volume):
        """Creates a volume."""
        volpath = self.common.create_volume(volume)

        model_update = {}
        volume['provider_location'] = six.text_type(volpath)
        model_update['provider_location'] = volume['provider_location']
        return model_update

    @lockutils.synchronized('ETERNUS_DX-vol', 'cinder-', True)
    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        volpath = self.common.create_volume_from_snapshot(volume, snapshot)

        model_update = {}
        volume['provider_location'] = six.text_type(volpath)
        model_update['provider_location'] = volume['provider_location']
        return model_update

    @lockutils.synchronized('ETERNUS_DX-vol', 'cinder-', True)
    def create_cloned_volume(self, volume, src_vref):
        """Creates a cloned volume."""
        volpath = self.common.create_cloned_volume(volume, src_vref)

        model_update = {}
        volume['provider_location'] = six.text_type(volpath)
        model_update['provider_location'] = volume['provider_location']
        return model_update

    @lockutils.synchronized('ETERNUS_DX-vol', 'cinder-', True)
    def delete_volume(self, volume):
        """Deletes a volume."""
        self.common.delete_volume(volume)

    @lockutils.synchronized('ETERNUS_DX-vol', 'cinder-', True)
    def create_snapshot(self, snapshot):
        """Creates a snapshot."""

        ctxt = context.get_admin_context()
        volumename = snapshot['volume_name']
        index = volumename.index('-')
        volumeid = volumename[index + 1:]
        volume = self.db.volume_get(ctxt, volumeid)

        volpath = self.common.create_snapshot(snapshot, volume)

        model_update = {}
        snapshot['provider_location'] = six.text_type(volpath)
        model_update['provider_location'] = snapshot['provider_location']
        return model_update

    @lockutils.synchronized('ETERNUS_DX-vol', 'cinder-', True)
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""

        self.common.delete_volume(snapshot)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        pass

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        pass

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        pass

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    @fczm_utils.AddFCZone
    @lockutils.synchronized('ETERNUS_DX-vol', 'cinder-', True)
    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        Assign any created volume to a compute node/host so that it can be
        used from that host.

        The  driver returns a driver_volume_type of 'fibre_channel'.
        The target_wwn can be a single entry or a list of wwns that
        correspond to the list of remote wwn(s) that will export the volume.
        Example return values:

            {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': '1234567890123',
                }
            }

            or

             {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': ['1234567890123', '0987654321321'],
                }
            }

        """
        device_info = self.common.initialize_connection(volume,
                                                        connector)
        device_number = device_info['hostlunid']
        storage_system = device_info['storagesystem']
        target_wwns, init_targ_map = self._build_initiator_target_map(
            storage_system, connector)

        data = {'driver_volume_type': 'fibre_channel',
                'data': {'target_lun': device_number,
                         'target_discovered': True,
                         'target_wwn': target_wwns,
                         'initiator_target_map': init_targ_map}}

        LOG.debug('Return FC data: %(data)s.'
                  % {'data': data})

        return data

    @fczm_utils.RemoveFCZone
    @lockutils.synchronized('ETERNUS_DX-vol', 'cinder-', True)
    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        ctrl = self.common.terminate_connection(volume, connector)

        loc = volume['provider_location']
        name = eval(loc)
        storage_system = name['keybindings']['SystemName']
        target_wwns, init_targ_map = self._build_initiator_target_map(
            storage_system, connector)

        data = {'driver_volume_type': 'fibre_channel',
                'data': {}}

        if len(ctrl) == 0:
            # No more volumes attached to the host
            data['data'] = {'target_wwn': target_wwns,
                            'initiator_target_map': init_targ_map}

        LOG.debug('Return FC data: %(data)s.'
                  % {'data': data})

        return data

    def _build_initiator_target_map(self, storage_system, connector):
        """Build the target_wwns and the initiator target map."""

        target_wwns = self.common.get_target_portid(connector)

        initiator_wwns = connector['wwpns']

        init_targ_map = {}
        for initiator in initiator_wwns:
            init_targ_map[initiator] = target_wwns

        return target_wwns, init_targ_map

    @lockutils.synchronized('ETERNUS_DX-vol', 'cinder-', True)
    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        self.common.extend_volume(volume, new_size)

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self.update_volume_stats()

        return self._stats

    def update_volume_stats(self):
        """Retrieve stats info from volume group."""
        LOG.debug("Updating volume stats")
        data = self.common.update_volume_stats()
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or 'FJDXFCDriver'
        data['storage_protocol'] = 'FC'
        data['driver_version'] = self.VERSION
        self._stats = data
