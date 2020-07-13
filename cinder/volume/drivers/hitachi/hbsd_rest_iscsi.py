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
"""REST interface iSCSI module for Hitachi HBSD Driver."""

from oslo_log import log as logging

from cinder.volume.drivers.hitachi import hbsd_rest as rest
from cinder.volume.drivers.hitachi import hbsd_utils as utils

_ISCSI_HMO_REPORT_FULL_PORTAL = 83
_ISCSI_HMO_DISABLE_IO = 91

LOG = logging.getLogger(__name__)
MSG = utils.HBSDMsg


class HBSDRESTISCSI(rest.HBSDREST):
    """REST interface iscsi class for Hitachi HBSD Driver."""

    def _set_target_portal(self, port):
        """Get port info and store it in an instance variable."""
        result = self.client.get_port(port)
        ipv4_addr = result.get('ipv4Address')
        tcp_port = result.get('tcpPort')
        if not ipv4_addr or not tcp_port:
            return False, ipv4_addr, tcp_port
        self.storage_info['portals'][port] = '%(ip)s:%(port)s' % {
            'ip': ipv4_addr,
            'port': tcp_port,
        }
        return True, ipv4_addr, tcp_port

    def connect_storage(self):
        """Prepare for using the storage."""
        target_ports = self.conf.hitachi_target_ports
        compute_target_ports = self.conf.hitachi_compute_target_ports

        super(HBSDRESTISCSI, self).connect_storage()
        # The port type must be ISCSI and the port attributes must contain TAR.
        params = {'portType': 'ISCSI',
                  'portAttributes': 'TAR'}
        port_list = self.client.get_ports(params=params)
        for port in set(target_ports + compute_target_ports):
            if port not in [port_data['portId'] for port_data in port_list]:
                utils.output_log(
                    MSG.INVALID_PORT, port=port, additional_info='(portType, '
                    'portAttributes): not (ISCSI, TAR)')
        for port_data in port_list:
            port = port_data['portId']
            if port not in set(target_ports + compute_target_ports):
                continue
            has_addr = True
            if not port_data['lunSecuritySetting']:
                addr_info = ""
            elif port in set(target_ports + compute_target_ports):
                has_addr, ipv4_addr, tcp_port = self._set_target_portal(port)
                if not has_addr:
                    addr_info = (', ipv4Address: %s, tcpPort: %s' %
                                 (ipv4_addr, tcp_port))
            if not port_data['lunSecuritySetting'] or not has_addr:
                utils.output_log(
                    MSG.INVALID_PORT, port=port,
                    additional_info='portType: %s, lunSecuritySetting: %s%s' %
                    (port_data['portType'], port_data['lunSecuritySetting'],
                     addr_info))
            if not port_data['lunSecuritySetting']:
                continue
            if target_ports and port in target_ports and has_addr:
                self.storage_info['controller_ports'].append(port)
            if (compute_target_ports and port in compute_target_ports and
                    has_addr):
                self.storage_info['compute_ports'].append(port)

        self.check_ports_info()
        utils.output_log(MSG.SET_CONFIG_VALUE,
                         object='port-<IP address:port> list',
                         value=self.storage_info['portals'])

    def create_target_to_storage(self, port, connector, hba_ids):
        """Create an iSCSI target on the specified port."""
        target_name = '%(prefix)s-%(ip)s' % {
            'prefix': utils.DRIVER_PREFIX,
            'ip': connector['ip'],
        }
        body = {'portId': port, 'hostGroupName': target_name}
        if hba_ids:
            body['iscsiName'] = '%(id)s%(suffix)s' % {
                'id': hba_ids,
                'suffix': utils.TARGET_IQN_SUFFIX,
            }
        try:
            gid = self.client.add_host_grp(body, no_log=True)
        except Exception:
            params = {'portId': port}
            host_grp_list = self.client.get_host_grps(params)
            for host_grp_data in host_grp_list:
                if host_grp_data['hostGroupName'] == target_name:
                    return target_name, host_grp_data['hostGroupNumber']
            else:
                raise
        return target_name, gid

    def set_hba_ids(self, port, gid, hba_ids):
        """Connect the specified HBA with the specified port."""
        self.client.add_hba_iscsi(port, gid, hba_ids)

    def set_target_mode(self, port, gid):
        """Configure the iSCSI target to meet the environment."""
        body = {'hostMode': 'LINUX/IRIX',
                'hostModeOptions': [_ISCSI_HMO_REPORT_FULL_PORTAL,
                                    _ISCSI_HMO_DISABLE_IO]}
        self.client.modify_host_grp(port, gid, body)

    def _is_host_iqn_registered_in_target(self, port, gid, host_iqn):
        """Check if the specified IQN is registered with iSCSI target."""
        for hba_iscsi in self.client.get_hba_iscsis(port, gid):
            if host_iqn == hba_iscsi['iscsiName']:
                return True
        return False

    def _set_target_info(self, targets, host_grps, iqn):
        """Set the information of the iSCSI target having the specified IQN."""
        for host_grp in host_grps:
            port = host_grp['portId']
            gid = host_grp['hostGroupNumber']
            storage_iqn = host_grp['iscsiName']
            if self._is_host_iqn_registered_in_target(port, gid, iqn):
                targets['info'][port] = True
                targets['list'].append((port, gid))
                targets['iqns'][(port, gid)] = storage_iqn
                return True
        return False

    def _get_host_iqn_registered_in_target_by_name(
            self, port, target_name, host_iqn):
        """Get the information of the iSCSI target having the specified name

        and the specified IQN.
        """
        for hba_iscsi in self.client.get_hba_iscsis_by_name(port, target_name):
            if host_iqn == hba_iscsi['iscsiName']:
                return hba_iscsi
        return None

    def _set_target_info_by_name(self, targets, port, target_name, iqn):
        """Set the information of the iSCSI target having the specified name

        and the specified IQN.
        """
        host_iqn_registered_in_target = (
            self._get_host_iqn_registered_in_target_by_name(
                port, target_name, iqn))
        if host_iqn_registered_in_target:
            gid = host_iqn_registered_in_target['hostGroupNumber']
            storage_iqn = self.client.get_host_grp(port, gid)['iscsiName']
            targets['info'][port] = True
            targets['list'].append((port, gid))
            targets['iqns'][(port, gid)] = storage_iqn
            return True
        return False

    def find_targets_from_storage(self, targets, connector, target_ports):
        """Find mapped ports, memorize them and return unmapped port count."""
        iqn = self.get_hba_ids_from_connector(connector)
        not_found_count = 0
        for port in target_ports:
            targets['info'][port] = False
            if 'ip' in connector:
                target_name = '%(prefix)s-%(ip)s' % {
                    'prefix': utils.DRIVER_PREFIX,
                    'ip': connector['ip'],
                }
                if self._set_target_info_by_name(
                        targets, port, target_name, iqn):
                    continue
            host_grps = self.client.get_host_grps({'portId': port})
            if 'ip' in connector:
                host_grps = [hg for hg in host_grps
                             if hg['hostGroupName'] != target_name]
            if self._set_target_info(targets, host_grps, iqn):
                pass
            else:
                not_found_count += 1
        return not_found_count

    def get_properties_iscsi(self, targets, multipath):
        """Return iSCSI-specific server-LDEV connection info."""
        if not multipath:
            target_list = targets['list'][:1]
        else:
            target_list = targets['list'][:]

        for target in target_list:
            if target not in targets['iqns']:
                port, gid = target
                target_info = self.client.get_host_grp(port, gid)
                iqn = target_info.get('iscsiName') if target_info else None
                if not iqn:
                    msg = utils.output_log(MSG.RESOURCE_NOT_FOUND,
                                           resource='Target IQN')
                    raise utils.HBSDError(msg)
                targets['iqns'][target] = iqn
                LOG.debug(
                    'Found target iqn of host group. (port: %(port)s, '
                    'gid: %(gid)s, target iqn: %(iqn)s)',
                    {'port': port, 'gid': gid, 'iqn': iqn})
        return super(HBSDRESTISCSI, self).get_properties_iscsi(
            targets, multipath)

    def _get_iqn(self, port, hostgroup):
        """Get IQN from a port and the ISCSI target."""
        hba_iscsis = self.client.get_hba_iscsis_by_name(port, hostgroup)
        return hba_iscsis[0]['iscsiName']

    def set_terminate_target(self, fake_connector, port_hostgroup_map):
        """Set necessary information in connector in terminate."""
        for port, hostgroups in port_hostgroup_map.items():
            for hostgroup in hostgroups:
                iqn = self._get_iqn(port, hostgroup)
                if iqn:
                    fake_connector['initiator'] = iqn
                    return
