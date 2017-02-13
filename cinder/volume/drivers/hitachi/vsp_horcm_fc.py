# Copyright (C) 2016, Hitachi, Ltd.
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
"""HORCM interface fibre channel module for Hitachi VSP Driver."""

import re

from oslo_log import log as logging

from cinder import exception
from cinder.volume.drivers.hitachi import vsp_horcm as horcm
from cinder.volume.drivers.hitachi import vsp_utils as utils
from cinder.zonemanager import utils as fczm_utils

_FC_LINUX_MODE_OPTS = ['-host_mode', 'LINUX']
_HOST_GROUPS_PATTERN = re.compile(
    r"^CL\w-\w+ +(?P<gid>\d+) +%s(?!pair00 )\S* +\d+ " % utils.TARGET_PREFIX,
    re.M)
_FC_PORT_PATTERN = re.compile(
    (r"^(CL\w-\w)\w* +(?:FIBRE|FCoE) +TAR +\w+ +\w+ +\w +\w+ +Y +"
     r"\d+ +\d+ +(\w{16})"), re.M)

LOG = logging.getLogger(__name__)
MSG = utils.VSPMsg


class VSPHORCMFC(horcm.VSPHORCM):
    """HORCM interface fibre channel class for Hitachi VSP Driver."""

    def __init__(self, conf, storage_protocol, db):
        """Initialize instance variables."""
        super(VSPHORCMFC, self).__init__(conf, storage_protocol, db)
        self._lookup_service = fczm_utils.create_lookup_service()

    def connect_storage(self):
        """Prepare for using the storage."""
        target_ports = self.conf.vsp_target_ports
        compute_target_ports = self.conf.vsp_compute_target_ports
        pair_target_ports = self.conf.vsp_horcm_pair_target_ports

        super(VSPHORCMFC, self).connect_storage()
        result = self.run_raidcom('get', 'port')
        for port, wwn in _FC_PORT_PATTERN.findall(result[1]):
            if target_ports and port in target_ports:
                self.storage_info['controller_ports'].append(port)
                self.storage_info['wwns'][port] = wwn
            if compute_target_ports and port in compute_target_ports:
                self.storage_info['compute_ports'].append(port)
                self.storage_info['wwns'][port] = wwn
            if pair_target_ports and port in pair_target_ports:
                self.storage_info['pair_ports'].append(port)

        self.check_ports_info()
        if pair_target_ports and not self.storage_info['pair_ports']:
            msg = utils.output_log(MSG.RESOURCE_NOT_FOUND,
                                   resource="Pair target ports")
            raise exception.VSPError(msg)
        utils.output_log(MSG.SET_CONFIG_VALUE,
                         object='pair target port list',
                         value=self.storage_info['pair_ports'])
        utils.output_log(MSG.SET_CONFIG_VALUE, object='port-wwn list',
                         value=self.storage_info['wwns'])

    def create_target_to_storage(self, port, connector, hba_ids):
        """Create a host group on the specified port."""
        wwpns = self.get_hba_ids_from_connector(connector)
        target_name = utils.TARGET_PREFIX + min(wwpns)
        try:
            result = self.run_raidcom(
                'add', 'host_grp', '-port', port, '-host_grp_name',
                target_name)
        except exception.VSPError:
            result = self.run_raidcom('get', 'host_grp', '-port', port)
            hostgroup_pt = re.compile(
                r"^CL\w-\w+ +(?P<gid>\d+) +%s +\d+ " %
                target_name, re.M)
            gid = hostgroup_pt.findall(result[1])
            if gid:
                return target_name, gid[0]
            else:
                raise
        return target_name, horcm.find_value(result[1], 'gid')

    def set_hba_ids(self, port, gid, hba_ids):
        """Connect all specified HBAs with the specified port."""
        registered_wwns = []
        for wwn in hba_ids:
            try:
                self.run_raidcom(
                    'add', 'hba_wwn', '-port',
                    '-'.join([port, gid]), '-hba_wwn', wwn)
                registered_wwns.append(wwn)
            except exception.VSPError:
                utils.output_log(MSG.ADD_HBA_WWN_FAILED, port=port, gid=gid,
                                 wwn=wwn)
        if not registered_wwns:
            msg = utils.output_log(MSG.NO_HBA_WWN_ADDED_TO_HOST_GRP, port=port,
                                   gid=gid)
            raise exception.VSPError(msg)

    def set_target_mode(self, port, gid):
        """Configure the host group to meet the environment."""
        self.run_raidcom(
            'modify', 'host_grp', '-port',
            '-'.join([port, gid]), *_FC_LINUX_MODE_OPTS,
            success_code=horcm.ALL_EXIT_CODE)

    def find_targets_from_storage(self, targets, connector, target_ports):
        """Find mapped ports, memorize them and return unmapped port count."""
        nr_not_found = 0
        old_target_name = None
        if 'ip' in connector:
            old_target_name = utils.TARGET_PREFIX + connector['ip']
        success_code = horcm.HORCM_EXIT_CODE.union([horcm.EX_ENOOBJ])
        wwpns = self.get_hba_ids_from_connector(connector)
        wwpns_pattern = re.compile(
            r'^CL\w-\w+ +\d+ +\S+ +(%s) ' % '|'.join(wwpns), re.M | re.I)
        target_name = utils.TARGET_PREFIX + min(wwpns)

        for port in target_ports:
            targets['info'][port] = False

            result = self.run_raidcom(
                'get', 'hba_wwn', '-port', port, target_name,
                success_code=success_code)
            wwpns = wwpns_pattern.findall(result[1])
            if not wwpns and old_target_name:
                result = self.run_raidcom(
                    'get', 'hba_wwn', '-port', port, old_target_name,
                    success_code=success_code)
                wwpns = wwpns_pattern.findall(result[1])
            if wwpns:
                gid = result[1].splitlines()[1].split()[1]
                targets['info'][port] = True
                targets['list'].append((port, gid))
                LOG.debug(
                    'Found wwpns in host group immediately. '
                    '(port: %(port)s, gid: %(gid)s, wwpns: %(wwpns)s)',
                    {'port': port, 'gid': gid, 'wwpns': wwpns})
                continue

            result = self.run_raidcom(
                'get', 'host_grp', '-port', port)
            for gid in _HOST_GROUPS_PATTERN.findall(result[1]):
                result = self.run_raidcom(
                    'get', 'hba_wwn', '-port', '-'.join([port, gid]))
                wwpns = wwpns_pattern.findall(result[1])
                if wwpns:
                    targets['info'][port] = True
                    targets['list'].append((port, gid))
                    LOG.debug(
                        'Found wwpns in host group. (port: %(port)s, '
                        'gid: %(gid)s, wwpns: %(wwpns)s)',
                        {'port': port, 'gid': gid, 'wwpns': wwpns})
                    break
            else:
                nr_not_found += 1

        return nr_not_found

    @fczm_utils.add_fc_zone
    def initialize_connection(self, volume, connector):
        """Initialize connection between the server and the volume."""
        conn_info = super(VSPHORCMFC, self).initialize_connection(
            volume, connector)
        if self.conf.vsp_zoning_request:
            utils.update_conn_info(conn_info, connector, self._lookup_service)
        return conn_info

    @fczm_utils.remove_fc_zone
    def terminate_connection(self, volume, connector):
        """Terminate connection between the server and the volume."""
        conn_info = super(VSPHORCMFC, self).terminate_connection(
            volume, connector)
        if self.conf.vsp_zoning_request and (
                conn_info and conn_info['data']['target_wwn']):
            utils.update_conn_info(conn_info, connector, self._lookup_service)
        return conn_info
