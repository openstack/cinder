# Copyright (c) 2013 Huawei Technologies Co., Ltd.
# Copyright (c) 2012 OpenStack Foundation
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
"""
Volume Drivers for Huawei OceanStor Dorado series storage arrays.
"""

import re

from cinder.openstack.common import log as logging
from cinder.volume.drivers.huawei import huawei_t
from cinder.volume.drivers.huawei import ssh_common

LOG = logging.getLogger(__name__)


class HuaweiDoradoISCSIDriver(huawei_t.HuaweiTISCSIDriver):
    """ISCSI driver class for Huawei OceanStor Dorado storage arrays."""

    def __init__(self, *args, **kwargs):
        super(HuaweiDoradoISCSIDriver, self).__init__(*args, **kwargs)

    def do_setup(self, context):
        """Instantiate common class."""
        self.common = ssh_common.DoradoCommon(configuration=self.configuration)

        self.common.do_setup(context)
        self._assert_cli_out = self.common._assert_cli_out
        self._assert_cli_operate_out = self.common._assert_cli_operate_out


class HuaweiDoradoFCDriver(huawei_t.HuaweiTFCDriver):
    """FC driver class for Huawei OceanStor Dorado storage arrays."""

    def __init__(self, *args, **kwargs):
        super(HuaweiDoradoFCDriver, self).__init__(*args, **kwargs)

    def do_setup(self, context):
        """Instantiate common class."""
        self.common = ssh_common.DoradoCommon(configuration=self.configuration)

        self.common.do_setup(context)
        self._assert_cli_out = self.common._assert_cli_out
        self._assert_cli_operate_out = self.common._assert_cli_operate_out

    def _get_host_port_details(self, hostid):
        cli_cmd = 'showfcmode'
        out = self.common._execute_cli(cli_cmd)

        self._assert_cli_out(re.search('FC Port Topology Mode', out),
                             '_get_tgt_fc_port_wwns',
                             'Failed to get FC port WWNs.',
                             cli_cmd, out)

        return [line.split()[3] for line in out.split('\r\n')[6:-2]]

    def _get_tgt_fc_port_wwns(self, port_details):
        return port_details

    def initialize_connection(self, volume, connector):
        """Create FC connection between a volume and a host."""
        LOG.debug('initialize_connection: volume name: %(vol)s '
                  'host: %(host)s initiator: %(wwn)s'
                  % {'vol': volume['name'],
                     'host': connector['host'],
                     'wwn': connector['wwpns']})

        self.common._update_login_info()
        # First, add a host if it is not added before.
        host_id = self.common.add_host(connector['host'], connector['ip'])
        # Then, add free FC ports to the host.
        ini_wwns = connector['wwpns']
        free_wwns = self._get_connected_free_wwns()
        for wwn in free_wwns:
            if wwn in ini_wwns:
                self._add_fc_port_to_host(host_id, wwn)
        fc_port_details = self._get_host_port_details(host_id)
        tgt_wwns = self._get_tgt_fc_port_wwns(fc_port_details)

        LOG.debug('initialize_connection: Target FC ports WWNS: %s'
                  % tgt_wwns)

        # Finally, map the volume to the host.
        volume_id = volume['provider_location']
        hostlun_id = self.common.map_volume(host_id, volume_id)

        properties = {}
        properties['target_discovered'] = False
        properties['target_wwn'] = tgt_wwns
        properties['target_lun'] = int(hostlun_id)
        properties['volume_id'] = volume['id']

        return {'driver_volume_type': 'fibre_channel',
                'data': properties}
