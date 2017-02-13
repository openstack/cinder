# Copyright (c) 2016 Huawei Technologies Co., Ltd.
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

import json

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.huawei import constants


LOG = logging.getLogger(__name__)


class FCZoneHelper(object):
    """FC zone helper for Huawei driver."""

    def __init__(self, fcsan_lookup_service, client):
        self.fcsan = fcsan_lookup_service
        self.client = client

    def _get_fc_ports_info(self):
        ports_info = {}
        data = self.client.get_fc_ports_on_array()
        for item in data:
            if item['RUNNINGSTATUS'] == constants.FC_PORT_CONNECTED:
                location = item['PARENTID'].split('.')
                port_info = {}
                port_info['id'] = item['ID']
                port_info['contr'] = location[0]
                port_info['bandwidth'] = item['RUNSPEED']
                ports_info[item['WWN']] = port_info
        return ports_info

    def _count_port_weight(self, port, ports_info):
        LOG.debug("Count weight for port: %s.", port)
        portgs = self.client.get_portgs_by_portid(ports_info[port]['id'])
        LOG.debug("Port %(port)s belongs to PortGroup %(portgs)s.",
                  {"port": port, "portgs": portgs})
        weight = 0
        for portg in portgs:
            views = self.client.get_views_by_portg(portg)
            if not views:
                LOG.debug("PortGroup %s doesn't belong to any view.", portg)
                continue

            LOG.debug("PortGroup %(portg)s belongs to view %(views)s.",
                      {"portg": portg, "views": views[0]})
            # In fact, there is just one view for one port group.
            lungroup = self.client.get_lungroup_by_view(views[0])
            lun_num = self.client.get_obj_count_from_lungroup(lungroup)
            ports_in_portg = self.client.get_ports_by_portg(portg)
            LOG.debug("PortGroup %(portg)s contains ports: %(ports)s.",
                      {"portg": portg, "ports": ports_in_portg})
            total_bandwidth = 0
            for port_pg in ports_in_portg:
                if port_pg in ports_info:
                    total_bandwidth += int(ports_info[port_pg]['bandwidth'])

            LOG.debug("Total bandwidth for PortGroup %(portg)s is %(bindw)s.",
                      {"portg": portg, "bindw": total_bandwidth})

            if total_bandwidth:
                weight += float(lun_num) / float(total_bandwidth)

        bandwidth = float(ports_info[port]['bandwidth'])
        return (weight, 10000 / bandwidth)

    def _get_weighted_ports_per_contr(self, ports, ports_info):
        port_weight_map = {}
        for port in ports:
            port_weight_map[port] = self._count_port_weight(port, ports_info)

        LOG.debug("port_weight_map: %s", port_weight_map)
        sorted_ports = sorted(port_weight_map.items(), key=lambda d: d[1])
        weighted_ports = []
        count = 0
        for port in sorted_ports:
            if count >= constants.PORT_NUM_PER_CONTR:
                break
            weighted_ports.append(port[0])
            count += 1
        return weighted_ports

    def _get_weighted_ports(self, contr_port_map, ports_info, contrs):
        LOG.debug("_get_weighted_ports, we only select ports from "
                  "controllers: %s", contrs)
        weighted_ports = []
        for contr in contrs:
            if contr in contr_port_map:
                weighted_ports_per_contr = self._get_weighted_ports_per_contr(
                    contr_port_map[contr], ports_info)
                LOG.debug("Selected ports %(ports)s on controller %(contr)s.",
                          {"ports": weighted_ports_per_contr,
                           "contr": contr})
                weighted_ports.extend(weighted_ports_per_contr)
        return weighted_ports

    def _filter_by_fabric(self, wwns, ports):
        """Filter FC ports and initiators connected to fabrics."""
        ini_tgt_map = self.fcsan.get_device_mapping_from_network(wwns, ports)
        fabric_connected_ports = []
        fabric_connected_initiators = []
        for fabric in ini_tgt_map:
            fabric_connected_ports.extend(
                ini_tgt_map[fabric]['target_port_wwn_list'])
            fabric_connected_initiators.extend(
                ini_tgt_map[fabric]['initiator_port_wwn_list'])

        if not fabric_connected_ports:
            msg = _("No FC port connected to fabric.")
            raise exception.VolumeBackendAPIException(data=msg)
        if not fabric_connected_initiators:
            msg = _("No initiator connected to fabric.")
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug("Fabric connected ports: %(ports)s, "
                  "Fabric connected initiators: %(initiators)s.",
                  {'ports': fabric_connected_ports,
                   'initiators': fabric_connected_initiators})
        return fabric_connected_ports, fabric_connected_initiators

    def _get_lun_engine_contrs(self, engines, lun_id,
                               lun_type=constants.LUN_TYPE):
        contrs = []
        engine_id = None
        lun_info = self.client.get_lun_info(lun_id, lun_type)
        lun_contr_id = lun_info['OWNINGCONTROLLER']
        for engine in engines:
            contrs = json.loads(engine['NODELIST'])
            engine_id = engine['ID']
            if lun_contr_id in contrs:
                break

        LOG.debug("LUN %(lun_id)s belongs to engine %(engine_id)s. Engine "
                  "%(engine_id)s has controllers: %(contrs)s.",
                  {"lun_id": lun_id, "engine_id": engine_id, "contrs": contrs})
        return contrs, engine_id

    def _build_contr_port_map(self, fabric_connected_ports, ports_info):
        contr_port_map = {}
        for port in fabric_connected_ports:
            contr = ports_info[port]['contr']
            if not contr_port_map.get(contr):
                contr_port_map[contr] = []
            contr_port_map[contr].append(port)
        LOG.debug("Controller port map: %s.", contr_port_map)
        return contr_port_map

    def _create_new_portg(self, portg_name, engine_id):
        portg_id = self.client.get_tgt_port_group(portg_name)
        if portg_id:
            LOG.debug("Found port group %s not belonged to any view, "
                      "deleting it.", portg_name)
            ports = self.client.get_fc_ports_by_portgroup(portg_id)
            for port_id in ports.values():
                self.client.remove_port_from_portgroup(portg_id, port_id)
            self.client.delete_portgroup(portg_id)
        description = constants.PORTGROUP_DESCRIP_PREFIX + engine_id
        new_portg_id = self.client.create_portg(portg_name, description)
        return new_portg_id

    def build_ini_targ_map(self, wwns, host_id, lun_id,
                           lun_type=constants.LUN_TYPE):
        engines = self.client.get_all_engines()
        LOG.debug("Get array engines: %s", engines)

        contrs, engine_id = self._get_lun_engine_contrs(engines, lun_id,
                                                        lun_type)

        # Check if there is already a port group in the view.
        # If yes and have already considered the engine,
        # we won't change anything about the port group and zone.
        view_name = constants.MAPPING_VIEW_PREFIX + host_id
        portg_name = constants.PORTGROUP_PREFIX + host_id
        view_id = self.client.find_mapping_view(view_name)
        portg_info = self.client.get_portgroup_by_view(view_id)
        portg_id = portg_info[0]['ID'] if portg_info else None

        init_targ_map = {}
        if portg_id:
            description = portg_info[0].get("DESCRIPTION", '')
            engines = description.replace(constants.PORTGROUP_DESCRIP_PREFIX,
                                          "")
            engines = engines.split(',')
            ports = self.client.get_fc_ports_by_portgroup(portg_id)
            if engine_id in engines:
                LOG.debug("Have already selected ports for engine %s, just "
                          "use them.", engine_id)
                return (list(ports.keys()), portg_id, init_targ_map)

        # Filter initiators and ports that connected to fabrics.
        ports_info = self._get_fc_ports_info()
        (fabric_connected_ports, fabric_connected_initiators) = (
            self._filter_by_fabric(wwns, ports_info.keys()))

        # Build a controller->ports map for convenience.
        contr_port_map = self._build_contr_port_map(fabric_connected_ports,
                                                    ports_info)
        # Get the 'best' ports for the given controllers.
        weighted_ports = self._get_weighted_ports(contr_port_map, ports_info,
                                                  contrs)
        if not weighted_ports:
            msg = _("No FC port can be used for LUN %s.") % lun_id
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Handle port group.
        port_list = [ports_info[port]['id'] for port in weighted_ports]

        if portg_id:
            # Add engine ID to the description of the port group.
            self.client.append_portg_desc(portg_id, engine_id)
            # Extend the weighted_ports to include the ports already in the
            # port group.
            weighted_ports.extend(list(ports.keys()))
        else:
            portg_id = self._create_new_portg(portg_name, engine_id)

        for port in port_list:
            self.client.add_port_to_portg(portg_id, port)

        for ini in fabric_connected_initiators:
            init_targ_map[ini] = weighted_ports
        LOG.debug("build_ini_targ_map: Port group name: %(portg_name)s, "
                  "init_targ_map: %(map)s.",
                  {"portg_name": portg_name,
                   "map": init_targ_map})
        return weighted_ports, portg_id, init_targ_map

    def get_init_targ_map(self, wwns, host_id):
        error_ret = ([], None, {})
        if not host_id:
            return error_ret

        view_name = constants.MAPPING_VIEW_PREFIX + host_id
        view_id = self.client.find_mapping_view(view_name)
        if not view_id:
            return error_ret
        port_group = self.client.get_portgroup_by_view(view_id)
        portg_id = port_group[0]['ID'] if port_group else None
        ports = self.client.get_fc_ports_by_portgroup(portg_id)
        for port_id in ports.values():
            self.client.remove_port_from_portgroup(portg_id, port_id)
        init_targ_map = {}
        for wwn in wwns:
            init_targ_map[wwn] = list(ports.keys())
        return list(ports.keys()), portg_id, init_targ_map
