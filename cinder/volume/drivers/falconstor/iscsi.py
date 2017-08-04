# Copyright (c) 2016 FalconStor, Inc.
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
"""Volume driver for FalconStor FSS storage system.

This driver requires FSS-8.00-8865 or later.
"""

from cinder import interface
import cinder.volume.driver
from cinder.volume.drivers.falconstor import fss_common

DEFAULT_ISCSI_PORT = 3260


@interface.volumedriver
class FSSISCSIDriver(fss_common.FalconstorBaseDriver,
                     cinder.volume.driver.ISCSIDriver):

    """Implements commands for FalconStor FSS ISCSI management.

    To enable the driver add the following line to the cinder configuration:
        volume_driver=cinder.volume.drivers.falconstor.iscsi.FSSISCSIDriver

    .. code: text

      Version history:
          1.0.0 - Initial driver
          1.0.1 - Fix copy_image_to_volume error.
          1.0.2 - Closes-Bug #1554184, add lun id type conversion in
                  initialize_connection
          1.03 -  merge source code
          1.04 -  Fixed  create_volume_from_snapshot(), create_cloned_volume()
                  metadata TypeError
          2.0.0 - Newton driver
                  -- fixed consisgroup commands error
          2.0.1   -- fixed bugs
          2.0.2   -- support Multipath
          3.0.0 - Ocata driver
                  -- fixed bugs
          4.0.0 - Pike driver
                  -- extend Cinder driver to utilize multiple FSS storage pools

    """

    VERSION = '4.0.0'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "FalconStor_CI"

    # TODO(smcginnis) Remove driver in Queens if CI issues are not
    # addressed.
    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        super(FSSISCSIDriver, self).__init__(*args, **kwargs)
        self._storage_protocol = "iSCSI"
        self._backend_name = (
            self.configuration.safe_get('volume_backend_name') or
            self.__class__.__name__)

    def initialize_connection(self, volume, connector, initiator_data=None):
        fss_hosts = []
        target_portal = []
        multipath = connector.get('multipath', False)
        fss_hosts.append(self.configuration.san_ip)

        if multipath:
            if self._check_multipath():
                fss_hosts.append(self.configuration.fss_san_secondary_ip)
            else:
                multipath = False

        for host in fss_hosts:
            iscsi_ip_port = "%s:%d" % (host, DEFAULT_ISCSI_PORT)
            target_portal.append(iscsi_ip_port)

        target_info = self.proxy.initialize_connection_iscsi(volume,
                                                             connector,
                                                             fss_hosts)
        properties = {}
        properties['target_discovered'] = True
        properties['discard'] = True
        properties['encrypted'] = False
        properties['qos_specs'] = None
        properties['access_mode'] = 'rw'
        properties['volume_id'] = volume['id']
        properties['target_iqn'] = target_info['iqn']
        properties['target_portal'] = target_portal[0]
        properties['target_lun'] = int(target_info['lun'])

        if multipath:
            properties['target_iqns'] = [target_info['iqn'],
                                         target_info['iqn']]
            properties['target_portals'] = target_portal
            properties['target_luns'] = [int(target_info['lun']),
                                         int(target_info['lun'])]

        return {'driver_volume_type': 'iscsi', 'data': properties}

    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate connection."""
        self.proxy.terminate_connection_iscsi(volume, connector)
