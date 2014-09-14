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
import six

from cinder import context
from cinder.openstack.common import log as logging
from cinder.volume import driver
from cinder.volume.drivers.emc import emc_vmax_common
from cinder.zonemanager import utils as fczm_utils


LOG = logging.getLogger(__name__)


class EMCVMAXFCDriver(driver.FibreChannelDriver):
    """EMC FC Drivers for VMAX using SMI-S.

    Version history:
        1.0.0 - Initial driver
        1.1.0 - Multiple pools and thick/thin provisioning,
                performance enhancement.
        2.0.0 - Add driver requirement functions
    """

    VERSION = "2.0.0"

    def __init__(self, *args, **kwargs):

        super(EMCVMAXFCDriver, self).__init__(*args, **kwargs)
        self.common = emc_vmax_common.EMCVMAXCommon(
            'FC',
            configuration=self.configuration)

    def check_for_setup_error(self):
        pass

    def create_volume(self, volume):
        """Creates a EMC(VMAX/VNX) volume."""
        volpath = self.common.create_volume(volume)

        model_update = {}
        volume['provider_location'] = six.text_type(volpath)
        model_update['provider_location'] = volume['provider_location']
        return model_update

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        volpath = self.common.create_volume_from_snapshot(volume, snapshot)

        model_update = {}
        volume['provider_location'] = six.text_type(volpath)
        model_update['provider_location'] = volume['provider_location']
        return model_update

    def create_cloned_volume(self, volume, src_vref):
        """Creates a cloned volume."""
        volpath = self.common.create_cloned_volume(volume, src_vref)

        model_update = {}
        volume['provider_location'] = six.text_type(volpath)
        model_update['provider_location'] = volume['provider_location']
        return model_update

    def delete_volume(self, volume):
        """Deletes an EMC volume."""
        self.common.delete_volume(volume)

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

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        ctxt = context.get_admin_context()
        volumename = snapshot['volume_name']
        index = volumename.index('-')
        volumeid = volumename[index + 1:]
        volume = self.db.volume_get(ctxt, volumeid)

        self.common.delete_snapshot(snapshot, volume)

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
        device_info = self.common.initialize_connection(
            volume, connector)
        device_number = device_info['hostlunid']
        storage_system = device_info['storagesystem']
        target_wwns, init_targ_map = self._build_initiator_target_map(
            storage_system, connector)

        data = {'driver_volume_type': 'fibre_channel',
                'data': {'target_lun': device_number,
                         'target_discovered': True,
                         'target_wwn': target_wwns,
                         'initiator_target_map': init_targ_map}}

        LOG.debug("Return FC data: %(data)s."
                  % {'data': data})

        return data

    @fczm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector.

        Return empty data if other volumes are in the same zone.
        The FibreChannel ZoneManager doesn't remove zones
        if there isn't an initiator_target_map in the
        return of terminate_connection.

        :returns: data - the target_wwns and initiator_target_map if the
                         zone is to be removed, otherwise empty
        """
        self.common.terminate_connection(volume, connector)

        loc = volume['provider_location']
        name = eval(loc)
        storage_system = name['keybindings']['SystemName']

        numVolumes = self.common.get_num_volumes_mapped(volume, connector)
        if numVolumes > 0:
            data = {'driver_volume_type': 'fibre_channel',
                    'data': {}}
        else:
            target_wwns, init_targ_map = self._build_initiator_target_map(
                storage_system, connector)
            data = {'driver_volume_type': 'fibre_channel',
                    'data': {'target_wwn': target_wwns,
                             'initiator_target_map': init_targ_map}}

        LOG.debug("Return FC data: %(data)s."
                  % {'data': data})

        return data

    def _build_initiator_target_map(self, storage_system, connector):
        """Build the target_wwns and the initiator target map."""

        target_wwns = self.common.get_target_wwns(storage_system, connector)

        initiator_wwns = connector['wwpns']

        init_targ_map = {}
        for initiator in initiator_wwns:
            init_targ_map[initiator] = target_wwns

        return target_wwns, init_targ_map

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
        data['storage_protocol'] = 'FC'
        data['driver_version'] = self.VERSION
        self._stats = data

    def migrate_volume(self, ctxt, volume, host):
        """Migrate a volume from one Volume Backend to another.

        :param self: reference to class
        :param ctxt:
        :param volume: the volume object including the volume_type_id
        :param host: the host dict holding the relevant target(destination)
                     information
        :returns: moved
        :returns: list
        """
        return self.common.migrate_volume(ctxt, volume, host)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Migrate volume to another host using retype.

        :param self: reference to class
        :param ctxt:
        :param volume: the volume object including the volume_type_id
        :param new_type: the new volume type.
        :param host: the host dict holding the relevant
                     target(destination) information
        :returns: moved
        "returns: list
        """
        return self.common.retype(ctxt, volume, new_type, diff, host)
