#  Copyright (C) 2021-2022 YADRO.
#  All rights reserved.
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

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.yadro.tatlin_common import TatlinCommonVolumeDriver
from cinder.volume.drivers.yadro.tatlin_exception import TatlinAPIException
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)


@interface.volumedriver
class TatlinISCSIVolumeDriver(TatlinCommonVolumeDriver, driver.ISCSIDriver):
    """ACCESS Tatlin ISCSI Driver.

    Executes commands relating to ISCSI.
    Supports creation of volumes.

    .. code-block:: none

     API version history:

        1.0 - Initial version.
    """

    VERSION = "1.0"

    SUPPORTS_ACTIVE_ACTIVE = True

    # ThirdPartySystems wiki
    CI_WIKI_NAME = "Yadro_Tatlin_Unified_CI"

    def __init__(self, vg_obj=None, *args, **kwargs):
        # Parent sets db, host, _execute and base config
        super(TatlinISCSIVolumeDriver, self).__init__(*args, **kwargs)
        if self.configuration:
            self.backend_name = (self.configuration.safe_get(
                'volume_backend_name') or 'TatlinISCSI')
        self.DRIVER_VOLUME_TYPE = 'iSCSI'

    @volume_utils.trace
    def initialize_connection(self, volume, connector):
        @utils.synchronized("tatlin-volume-connections-%s" % volume.name_id)
        def _initialize_connection():
            LOG.debug('Init %s with connector %s', volume.name_id, connector)
            eth_ports = self._get_ports_portals()
            current_host = self.find_current_host(connector['initiator'])
            self.add_volume_to_host(volume, current_host)
            mapped_lun = self._find_mapped_lun(
                volume.name_id, connector['initiator'])
            port_result = self.tatlin_api.get_volume_ports(volume.name_id)

            result = {
                'driver_volume_type': 'iscsi',
                'data': self._create_volume_data(port_result, eth_ports,
                                                 mapped_lun)
            }

            if self._is_cinder_host_connection(connector):
                self._connections.increment(volume.name_id)

            LOG.debug('Current connection info %s', result)
            return result

        return _initialize_connection()

    def _get_ports_portals(self):
        try:
            result = self.tatlin_api.get_port_portal("ip")
        except TatlinAPIException as exp:
            message = (_('Failed to get ports info due to %s') % exp.message)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        ports = {}
        for p in result:
            ipaddr = p['params']['ipaddress']
            if not ipaddr:
                continue
            iface = p['params']['ifname']
            if iface.startswith('p'):
                if self._export_ports and iface not in self._export_ports:
                    continue
                if iface not in ports:
                    ports[iface] = []
                ports[iface].append(ipaddr + ':3260')

        return ports

    def _create_volume_data(self, port_inf, eth_ports, lun_id):
        res = {'target_discovered': True, 'target_lun': lun_id}

        tatlin_version = self.tatlin_api.get_tatlin_version()

        if tatlin_version > (2, 3):
            if self._auth_method == 'CHAP':
                res['auth_method'] = 'CHAP'
                res['auth_username'] = self._chap_username
                res['auth_password'] = self._chap_password
        else:
            cred = self.tatlin_api.get_iscsi_cred()
            res['auth_method'] = 'CHAP'
            res['auth_username'] = cred['userid']
            res['auth_password'] = cred['password']

        target_luns = []
        target_iqns = []
        target_portals = []
        LOG.debug('Port data: %s', port_inf)
        for port in port_inf:
            if port['port'] not in eth_ports.keys():
                continue

            ips = eth_ports[port['port']]
            target_portals += ips

            luns = [lun_id for _ in ips]
            target_luns += luns

            if 'running' in port:
                target_iqns += port['wwn'] * len(port['running'])
            else:
                target_iqns += port['wwn']

        if not target_portals or not target_iqns or not target_luns:
            message = (_('Not enough connection data, '
                         'luns: %s, portals: %s, iqns: %s') %
                       target_luns, target_portals, target_iqns)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        res['target_lun'] = target_luns[0]
        res['target_luns'] = target_luns
        res['target_iqn'] = target_iqns[0]
        res['target_iqns'] = target_iqns
        res['target_portal'] = target_portals[0]
        res['target_portals'] = target_portals

        LOG.debug("Volume data = %s", res)
        return res

    def find_current_host(self, wwn):
        LOG.debug('Try to find host id for %s', wwn)

        gr_id = self.tatlin_api.get_host_group_id(self._host_group)

        group_info = self.tatlin_api.get_host_group_info(gr_id)
        LOG.debug('Group info for %s is %s', self._host_group, group_info)
        for host_id in group_info['host_ids']:
            if wwn in self.tatlin_api.get_host_info(host_id)['initiators']:
                LOG.debug('Found host %s for initiator %s', host_id, wwn)
                return host_id

        mess = _('Unable to find host for initiator %s' % wwn)
        LOG.error(mess)
        raise exception.VolumeBackendAPIException(message=mess)
