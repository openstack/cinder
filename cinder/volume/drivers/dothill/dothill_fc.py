#    Copyright 2014 Objectif Libre
#    Copyright 2015 DotHill Systems
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
#

from oslo_log import log as logging

import cinder.volume.driver
from cinder.volume.drivers.dothill import dothill_common
from cinder.volume.drivers.san import san
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


class DotHillFCDriver(cinder.volume.driver.FibreChannelDriver):
    """Openstack Fibre Channel cinder drivers for DotHill Arrays.

    Version history:
        0.1    - Base version developed for HPMSA FC drivers:
                    "https://github.com/openstack/cinder/tree/stable/juno/
                     cinder/volume/drivers/san/hp"
        1.0    - Version developed for DotHill arrays with the following
                 modifications:
                     - added support for v3 API(virtual pool feature)
                     - added support for retype volume
                     - added support for manage/unmanage volume
                     - added initiator target mapping in FC zoning
                     - added https support

    """

    VERSION = "1.0"

    def __init__(self, *args, **kwargs):
        super(DotHillFCDriver, self).__init__(*args, **kwargs)
        self.common = None
        self.configuration.append_config_values(dothill_common.common_opts)
        self.configuration.append_config_values(san.san_opts)
        self.lookup_service = fczm_utils.create_lookup_service()

    def _init_common(self):
        return dothill_common.DotHillCommon(self.configuration)

    def _check_flags(self):
        required_flags = ['san_ip', 'san_login', 'san_password']
        self.common.check_flags(self.configuration, required_flags)

    def do_setup(self, context):
        self.common = self._init_common()
        self._check_flags()
        self.common.do_setup(context)

    def check_for_setup_error(self):
        self._check_flags()

    def create_volume(self, volume):
        self.common.create_volume(volume)

    def create_volume_from_snapshot(self, volume, src_vref):
        self.common.create_volume_from_snapshot(volume, src_vref)

    def create_cloned_volume(self, volume, src_vref):
        self.common.create_cloned_volume(volume, src_vref)

    def delete_volume(self, volume):
        self.common.delete_volume(volume)

    @fczm_utils.AddFCZone
    def initialize_connection(self, volume, connector):
        self.common.client_login()
        try:
            data = {}
            data['target_lun'] = self.common.map_volume(volume,
                                                        connector,
                                                        'wwpns')

            ports, init_targ_map = self.get_init_targ_map(connector)
            data['target_discovered'] = True
            data['target_wwn'] = ports
            data['initiator_target_map'] = init_targ_map
            info = {'driver_volume_type': 'fibre_channel',
                    'data': data}
            return info
        finally:
            self.common.client_logout()

    @fczm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, **kwargs):
        self.common.unmap_volume(volume, connector, 'wwpns')
        info = {'driver_volume_type': 'fibre_channel', 'data': {}}
        if not self.common.client.list_luns_for_host(connector['wwpns'][0]):
            ports, init_targ_map = self.get_init_targ_map(connector)
            info['data'] = {'target_wwn': ports,
                            'initiator_target_map': init_targ_map}
        return info

    def get_init_targ_map(self, connector):
        init_targ_map = {}
        target_wwns = []
        ports = self.common.get_active_fc_target_ports()
        if self.lookup_service is not None:
            dev_map = self.lookup_service.get_device_mapping_from_network(
                connector['wwpns'],
                ports)
            for fabric_name in dev_map:
                fabric = dev_map[fabric_name]
                target_wwns += fabric['target_port_wwn_list']
                for initiator in fabric['initiator_port_wwn_list']:
                    if initiator not in init_targ_map:
                        init_targ_map[initiator] = []
                    init_targ_map[initiator] += fabric['target_port_wwn_list']
                    init_targ_map[initiator] = list(set(
                                                    init_targ_map[initiator]))
            target_wwns = list(set(target_wwns))
        else:
            initiator_wwns = connector['wwpns']
            target_wwns = ports
            for initiator in initiator_wwns:
                init_targ_map[initiator] = target_wwns

        return target_wwns, init_targ_map

    def get_volume_stats(self, refresh=False):
        stats = self.common.get_volume_stats(refresh)
        stats['storage_protocol'] = 'FC'
        stats['driver_version'] = self.VERSION
        backend_name = self.configuration.safe_get('volume_backend_name')
        stats['volume_backend_name'] = (backend_name or
                                        self.__class__.__name__)
        return stats

    def create_export(self, context, volume, connector):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def create_snapshot(self, snapshot):
        self.common.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        self.common.delete_snapshot(snapshot)

    def extend_volume(self, volume, new_size):
        self.common.extend_volume(volume, new_size)

    def retype(self, context, volume, new_type, diff, host):
        return self.common.retype(volume, new_type, diff, host)

    def manage_existing(self, volume, existing_ref):
        self.common.manage_existing(volume, existing_ref)

    def manage_existing_get_size(self, volume, existing_ref):
        return self.common.manage_existing_get_size(volume, existing_ref)

    def unmanage(self, volume):
        pass
