# Copyright (c) 2015 Huawei Technologies Co., Ltd.
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

from cinder.volume.drivers.huawei import constants

LOG = logging.getLogger(__name__)


class FCZoneHelper(object):
    """FC zone helper for Huawei driver."""

    def __init__(self, fcsan_lookup_service, restclient):
        self.fcsan_lookup_service = fcsan_lookup_service
        self.restclient = restclient

    def _get_fc_port_contr_map(self):
        port_list = []
        port_contr_map = {}
        data = self.restclient.get_fc_ports_on_array()
        for item in data:
            if item['RUNNINGSTATUS'] == constants.FC_PORT_CONNECTED:
                port_list.append(item['WWN'])
                location = item['PARENTID'].split('.')
                port_contr_map[item['WWN']] = location[0][1]
        return port_list, port_contr_map

    def _filter_port_by_contr(self, ports_in_fabric, port_contr_map):
        filtered_ports = []
        for contr in constants.CONTROLLER_LIST:
            found_port_per_contr = 0
            for port in ports_in_fabric:
                if port in port_contr_map and port_contr_map[port] == contr:
                    filtered_ports.append(port)
                    found_port_per_contr = found_port_per_contr + 1
                    # We select two ports per every controller.
                    if found_port_per_contr == 2:
                        break
        return filtered_ports

    def build_ini_targ_map(self, wwns):
        tgt_wwns = []
        init_targ_map = {}
        port_lists, port_contr_map = self._get_fc_port_contr_map()
        ini_tgt_map = (self.fcsan_lookup_service.
                       get_device_mapping_from_network(wwns, port_lists))

        for fabric in ini_tgt_map:
            ports_in_fabric = ini_tgt_map[fabric]['target_port_wwn_list']
            contr_filtered_ports = self._filter_port_by_contr(ports_in_fabric,
                                                              port_contr_map)
            tgt_wwns.extend(contr_filtered_ports)
            for ini in ini_tgt_map[fabric]['initiator_port_wwn_list']:
                init_targ_map[ini] = contr_filtered_ports

        return (list(set(tgt_wwns)), init_targ_map)
