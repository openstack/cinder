# Copyright (c) 2015 EMC Corporation.
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

from oslo_log import log as logging
import six

from cinder import context
from cinder.i18n import _LW
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
        2.1.0 - Add consistency group functions
    """

    VERSION = "2.1.0"

    def __init__(self, *args, **kwargs):

        super(EMCVMAXFCDriver, self).__init__(*args, **kwargs)
        self.common = emc_vmax_common.EMCVMAXCommon(
            'FC',
            configuration=self.configuration)
        self.zonemanager_lookup_service = fczm_utils.create_lookup_service()

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
            storage_system, volume, connector)

        data = {'driver_volume_type': 'fibre_channel',
                'data': {'target_lun': device_number,
                         'target_discovered': True,
                         'target_wwn': target_wwns,
                         'initiator_target_map': init_targ_map}}

        LOG.debug("Return FC data for zone addition: %(data)s.",
                  {'data': data})

        return data

    @fczm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector.

        Return empty data if other volumes are in the same zone.
        The FibreChannel ZoneManager doesn't remove zones
        if there isn't an initiator_target_map in the
        return of terminate_connection.

        :param volume: the volume object
        :param connector: the connector object
        :returns: dict -- the target_wwns and initiator_target_map if the
            zone is to be removed, otherwise empty
        """
        data = {'driver_volume_type': 'fibre_channel',
                'data': {}}
        loc = volume['provider_location']
        name = eval(loc)
        storage_system = name['keybindings']['SystemName']
        LOG.debug("Start FC detach process for volume: %(volume)s.",
                  {'volume': volume['name']})

        mvInstanceName = self.common.get_masking_view_by_volume(
            volume, connector)
        if mvInstanceName is not None:
            portGroupInstanceName = (
                self.common.get_port_group_from_masking_view(
                    mvInstanceName))

            LOG.debug("Found port group: %(portGroup)s "
                      "in masking view %(maskingView)s.",
                      {'portGroup': portGroupInstanceName,
                       'maskingView': mvInstanceName})

            self.common.terminate_connection(volume, connector)

            LOG.debug("Looking for masking views still associated with "
                      "Port Group %s.", portGroupInstanceName)
            mvInstances = self.common.get_masking_views_by_port_group(
                portGroupInstanceName)
            if len(mvInstances) > 0:
                LOG.debug("Found %(numViews)lu MaskingViews.",
                          {'numViews': len(mvInstances)})
            else:  # No views found.
                target_wwns, init_targ_map = self._build_initiator_target_map(
                    storage_system, volume, connector)
                LOG.debug("No MaskingViews were found. Deleting zone.")
                data = {'driver_volume_type': 'fibre_channel',
                        'data': {'target_wwn': target_wwns,
                                 'initiator_target_map': init_targ_map}}
            LOG.debug("Return FC data for zone removal: %(data)s.",
                      {'data': data})
        else:
            LOG.warn(_LW("Volume %(volume)s is not in any masking view."),
                     {'volume': volume['name']})
        return data

    def _build_initiator_target_map(self, storage_system, volume, connector):
        """Build the target_wwns and the initiator target map."""
        target_wwns = []
        init_targ_map = {}
        initiator_wwns = connector['wwpns']

        if self.zonemanager_lookup_service:
            fc_targets = self.common.get_target_wwns_from_masking_view(
                storage_system, volume, connector)
            mapping = (
                self.zonemanager_lookup_service.
                get_device_mapping_from_network(initiator_wwns, fc_targets))
            for entry in mapping:
                map_d = mapping[entry]
                target_wwns.extend(map_d['target_port_wwn_list'])
                for initiator in map_d['initiator_port_wwn_list']:
                    init_targ_map[initiator] = map_d['target_port_wwn_list']
        else:  # No lookup service, pre-zoned case.
            target_wwns = self.common.get_target_wwns(storage_system,
                                                      connector)
            for initiator in initiator_wwns:
                init_targ_map[initiator] = target_wwns

        return list(set(target_wwns)), init_targ_map

    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        self.common.extend_volume(volume, new_size)

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        :param refresh: boolean -- If True, run update the stats first.
        :returns: dict -- the stats dict
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

        :param ctxt: context
        :param volume: the volume object including the volume_type_id
        :param host: the host dict holding the relevant target(destination)
            information
        :returns: boolean -- Always returns True
        :returns: dict -- Empty dict {}
        """
        return self.common.migrate_volume(ctxt, volume, host)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Migrate volume to another host using retype.

        :param ctxt: context
        :param volume: the volume object including the volume_type_id
        :param new_type: the new volume type.
        :param diff: Unused parameter.
        :param host: the host dict holding the relevant
            target(destination) information
        :returns: boolean -- True if retype succeeded, False if error
        """
        return self.common.retype(ctxt, volume, new_type, diff, host)

    def create_consistencygroup(self, context, group):
        """Creates a consistencygroup."""
        self.common.create_consistencygroup(context, group)

    def delete_consistencygroup(self, context, group):
        """Deletes a consistency group."""
        volumes = self.db.volume_get_all_by_group(context, group['id'])
        return self.common.delete_consistencygroup(
            context, group, volumes)

    def create_cgsnapshot(self, context, cgsnapshot):
        """Creates a cgsnapshot."""
        return self.common.create_cgsnapshot(context, cgsnapshot, self.db)

    def delete_cgsnapshot(self, context, cgsnapshot):
        """Deletes a cgsnapshot."""
        return self.common.delete_cgsnapshot(context, cgsnapshot, self.db)
