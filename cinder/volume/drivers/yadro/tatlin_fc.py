#  Copyright, 2023, KNS Group LLC (YADRO)
#
#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

from oslo_log import log as logging

from cinder.common import constants
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.yadro import tatlin_common
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


@interface.volumedriver
class TatlinFCVolumeDriver(tatlin_common.TatlinCommonVolumeDriver,
                           driver.FibreChannelDriver):
    """ACCESS Tatlin FC Driver.

    Executes commands relating to FC.
    Supports creation of volumes.

    .. code-block:: none

     API version history:

        1.0 - Initial version.
    """

    VERSION = '1.0'

    SUPPORTS_ACTIVE_ACTIVE = True

    # ThirdPartySystems wiki
    CI_WIKI_NAME = "Yadro_Tatlin_Unified_CI"

    def __init__(self, *args, **kwargs):
        super(TatlinFCVolumeDriver, self).__init__(*args, **kwargs)
        self.backend_name = self.configuration.safe_get(
            'volume_backend_name') or 'TatlinFC'
        self.DRIVER_VOLUME_TYPE = constants.FC
        self._lookup_service = fczm_utils.create_lookup_service()

    def _create_connection_info(self, volume, connector):
        info = {
            'driver_volume_type': constants.FC_VARIANT_1,
            'data': self._create_volume_data(volume, connector)
        }
        return info

    def _get_ports_portals(self):
        result = self.tatlin_api.get_port_portal("fc")
        ports = {}
        for p in result:
            iface = p['params']['ifname']
            if self._export_ports and iface not in self._export_ports:
                continue
            ports.setdefault(iface, []).append(p['params']['wwpn'])
        return ports

    def _create_volume_data(self, volume, connector):
        if connector is None:
            return {}
        lun_id = self._find_mapped_lun(volume.name_id, connector)
        volume_ports = self.tatlin_api.get_volume_ports(volume.name_id)
        ports_portals = self._get_ports_portals()
        data = {
            'target_discovered': True,
            'target_lun': lun_id,
            'discard': False,
        }
        target_wwns = []
        for port in volume_ports:
            wwpns = ports_portals.get(port['port'])
            if not wwpns:
                continue
            target_wwns += [w.replace(':', '') for w in wwpns]

        data['target_wwn'] = target_wwns
        data['initiator_target_map'] = self._build_initiator_target_map(
            target_wwns, connector)
        return data

    def find_current_host(self, connector):
        wwns = connector['wwpns']
        LOG.debug('Try to find host id for %s', wwns)
        result = self.tatlin_api.get_all_hosts()
        for h in result:
            for wwn in h['initiators']:
                if wwn.replace(':', '') in wwns:
                    LOG.debug('Current host is %s', h['id'])
                    return h['id']
        message = _('Unable to get host information for wwns: %s') % str(wwns)
        LOG.error(message)
        raise exception.VolumeBackendAPIException(message=message)

    def _build_initiator_target_map(self, target_wwns, connector):
        result = {}

        if self._lookup_service:
            mapping = self._lookup_service.get_device_mapping_from_network(
                connector['wwpns'], target_wwns)
            for fabric in mapping.values():
                for initiator in fabric['initiator_port_wwn_list']:
                    result.setdefault(initiator, []).extend(
                        fabric['target_port_wwn_list'])
            result = {i: list(set(t)) for i, t in result.items()}
        else:
            result = dict.fromkeys(connector['wwpns'], target_wwns)

        return result
