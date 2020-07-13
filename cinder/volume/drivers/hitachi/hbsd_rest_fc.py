# Copyright (C) 2020, Hitachi, Ltd.
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
"""REST interface fibre channel module for Hitachi HBSD Driver."""

from oslo_log import log as logging

from cinder.volume.drivers.hitachi import hbsd_rest as rest
from cinder.volume.drivers.hitachi import hbsd_utils as utils
from cinder.zonemanager import utils as fczm_utils

_FC_HMO_DISABLE_IO = 91

LOG = logging.getLogger(__name__)
MSG = utils.HBSDMsg


class HBSDRESTFC(rest.HBSDREST):
    """REST interface fibre channel class for Hitachi HBSD Driver."""

    def __init__(self, conf, storage_protocol, db):
        """Initialize instance variables."""
        super(HBSDRESTFC, self).__init__(conf, storage_protocol, db)
        self._lookup_service = fczm_utils.create_lookup_service()

    def connect_storage(self):
        """Prepare for using the storage."""
        target_ports = self.conf.hitachi_target_ports
        compute_target_ports = self.conf.hitachi_compute_target_ports
        available_ports = []
        available_compute_ports = []

        super(HBSDRESTFC, self).connect_storage()
        # The port attributes must contain TAR.
        params = {'portAttributes': 'TAR'}
        port_list = self.client.get_ports(params=params)
        for port in set(target_ports + compute_target_ports):
            if port not in [port_data['portId'] for port_data in port_list]:
                utils.output_log(MSG.INVALID_PORT, port=port,
                                 additional_info='portAttributes: not TAR')
        for port_data in port_list:
            port = port_data['portId']
            if port not in set(target_ports + compute_target_ports):
                continue
            secure_fc_port = True
            if (port_data['portType'] not in ['FIBRE', 'FCoE'] or
                    not port_data['lunSecuritySetting']):
                secure_fc_port = False
            if not secure_fc_port:
                utils.output_log(
                    MSG.INVALID_PORT, port=port,
                    additional_info='portType: %s, lunSecuritySetting: %s, '
                    'fabricMode: %s, portConnection: %s' %
                    (port_data['portType'],
                     port_data.get('lunSecuritySetting'),
                     port_data.get('fabricMode'),
                     port_data.get('portConnection')))
            if not secure_fc_port:
                continue
            wwn = port_data.get('wwn')
            if target_ports and port in target_ports:
                available_ports.append(port)
                self.storage_info['wwns'][port] = wwn
            if compute_target_ports and port in compute_target_ports:
                available_compute_ports.append(port)
                self.storage_info['wwns'][port] = wwn

        if target_ports:
            for port in target_ports:
                if port in available_ports:
                    self.storage_info['controller_ports'].append(port)
        if compute_target_ports:
            for port in compute_target_ports:
                if port in available_compute_ports:
                    self.storage_info['compute_ports'].append(port)

        self.check_ports_info()
        utils.output_log(MSG.SET_CONFIG_VALUE, object='port-wwn list',
                         value=self.storage_info['wwns'])

    def create_target_to_storage(self, port, connector, hba_ids):
        """Create a host group on the specified port."""
        wwpns = self.get_hba_ids_from_connector(connector)
        target_name = '%(prefix)s-%(wwpns)s' % {
            'prefix': utils.DRIVER_PREFIX,
            'wwpns': min(wwpns),
        }
        try:
            body = {'portId': port,
                    'hostGroupName': target_name}
            gid = self.client.add_host_grp(body, no_log=True)
        except Exception:
            params = {'portId': port}
            host_grp_list = self.client.get_host_grps(params)
            for host_grp_data in host_grp_list:
                if host_grp_data['hostGroupName'] == target_name:
                    return target_name, host_grp_data['hostGroupNumber']
            raise
        return target_name, gid

    def set_hba_ids(self, port, gid, hba_ids):
        """Connect all specified HBAs with the specified port."""
        registered_wwns = []
        for wwn in hba_ids:
            try:
                self.client.add_hba_wwn(port, gid, wwn, no_log=True)
                registered_wwns.append(wwn)
            except utils.HBSDError:
                utils.output_log(MSG.ADD_HBA_WWN_FAILED, port=port, gid=gid,
                                 wwn=wwn)
        if not registered_wwns:
            msg = utils.output_log(MSG.NO_HBA_WWN_ADDED_TO_HOST_GRP, port=port,
                                   gid=gid)
            raise utils.HBSDError(msg)

    def set_target_mode(self, port, gid):
        """Configure the host group to meet the environment."""
        body = {'hostMode': 'LINUX/IRIX',
                'hostModeOptions': [_FC_HMO_DISABLE_IO]}
        self.client.modify_host_grp(port, gid, body, ignore_all_errors=True)

    def _get_hwwns_in_hostgroup(self, port, gid, wwpns):
        """Return WWN registered with the host group."""
        hwwns_in_hostgroup = []
        for hba_wwn in self.client.get_hba_wwns(port, gid):
            hwwn = hba_wwn['hostWwn']
            if hwwn in wwpns:
                hwwns_in_hostgroup.append(hwwn)
        return hwwns_in_hostgroup

    def _set_target_info(self, targets, host_grps, wwpns):
        """Set the information of the host group having the specified WWN."""
        for host_grp in host_grps:
            port = host_grp['portId']
            gid = host_grp['hostGroupNumber']
            hwwns_in_hostgroup = self._get_hwwns_in_hostgroup(port, gid, wwpns)
            if hwwns_in_hostgroup:
                targets['info'][port] = True
                targets['list'].append((port, gid))
                LOG.debug(
                    'Found wwpns in host group. (port: %(port)s, '
                    'gid: %(gid)s, wwpns: %(wwpns)s)',
                    {'port': port, 'gid': gid, 'wwpns': hwwns_in_hostgroup})
                return True
        return False

    def _get_hwwns_in_hostgroup_by_name(self, port, host_group_name, wwpns):
        """Return WWN registered with the host group of the specified name."""
        hba_wwns = self.client.get_hba_wwns_by_name(port, host_group_name)
        return [hba_wwn for hba_wwn in hba_wwns if hba_wwn['hostWwn'] in wwpns]

    def _set_target_info_by_names(self, targets, port, target_names, wwpns):
        """Set the information of the host group having the specified name and

        the specified WWN.
        """
        for target_name in target_names:
            hwwns_in_hostgroup = self._get_hwwns_in_hostgroup_by_name(
                port, target_name, wwpns)
            if hwwns_in_hostgroup:
                gid = hwwns_in_hostgroup[0]['hostGroupNumber']
                targets['info'][port] = True
                targets['list'].append((port, gid))
                LOG.debug(
                    'Found wwpns in host group. (port: %(port)s, '
                    'gid: %(gid)s, wwpns: %(wwpns)s)',
                    {'port': port, 'gid': gid, 'wwpns':
                     [hwwn['hostWwn'] for hwwn in hwwns_in_hostgroup]})
                return True
        return False

    def find_targets_from_storage(
            self, targets, connector, target_ports):
        """Find mapped ports, memorize them and return unmapped port count."""
        wwpns = self.get_hba_ids_from_connector(connector)
        target_names = [
            '%(prefix)s-%(wwpns)s' % {
                'prefix': utils.DRIVER_PREFIX,
                'wwpns': min(wwpns),
            }
        ]
        if 'ip' in connector:
            target_names.append(
                '%(prefix)s-%(ip)s' % {
                    'prefix': utils.DRIVER_PREFIX,
                    'ip': connector['ip'],
                }
            )
        not_found_count = 0
        for port in target_ports:
            targets['info'][port] = False
            if self._set_target_info_by_names(
                    targets, port, target_names, wwpns):
                continue
            host_grps = self.client.get_host_grps({'portId': port})
            if self._set_target_info(
                targets, [hg for hg in host_grps if hg['hostGroupName'] not in
                          target_names], wwpns):
                pass
            else:
                not_found_count += 1
        return not_found_count

    def initialize_connection(self, volume, connector):
        """Initialize connection between the server and the volume."""
        conn_info = super(HBSDRESTFC, self).initialize_connection(
            volume, connector)
        if self.conf.hitachi_zoning_request:
            init_targ_map = utils.build_initiator_target_map(
                connector, conn_info['data']['target_wwn'],
                self._lookup_service)
            if init_targ_map:
                conn_info['data']['initiator_target_map'] = init_targ_map
            fczm_utils.add_fc_zone(conn_info)
        return conn_info

    def terminate_connection(self, volume, connector):
        """Terminate connection between the server and the volume."""
        conn_info = super(HBSDRESTFC, self).terminate_connection(
            volume, connector)
        if self.conf.hitachi_zoning_request:
            if conn_info and conn_info['data']['target_wwn']:
                init_targ_map = utils.build_initiator_target_map(
                    connector, conn_info['data']['target_wwn'],
                    self._lookup_service)
                if init_targ_map:
                    conn_info['data']['initiator_target_map'] = init_targ_map
            fczm_utils.remove_fc_zone(conn_info)
        return conn_info

    def _get_wwpns(self, port, hostgroup):
        """Get WWPN from a port and the host group."""
        wwpns = []
        hba_wwns = self.client.get_hba_wwns_by_name(port, hostgroup)
        for hba_wwn in hba_wwns:
            wwpns.append(hba_wwn['hostWwn'])
        return wwpns

    def set_terminate_target(self, fake_connector, port_hostgroup_map):
        """Set necessary information in connector in terminate."""
        wwpns = set()
        for port, hostgroups in port_hostgroup_map.items():
            for hostgroup in hostgroups:
                wwpns.update(self._get_wwpns(port, hostgroup))
        fake_connector['wwpns'] = list(wwpns)
