# Copyright 2020 toyou Corp.
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
acs5000 iSCSI driver
"""

from oslo_log import log as logging

from cinder import exception
from cinder import interface
from cinder import utils
from cinder.volume.drivers.toyou.acs5000 import acs5000_common

LOG = logging.getLogger(__name__)


@interface.volumedriver
class Acs5000ISCSIDriver(acs5000_common.Acs5000CommonDriver):
    """TOYOU ACS5000 storage iSCSI volume driver.

    .. code-block:: none

      Version history:
          1.0.0 - Initial driver

    """

    VENDOR = 'TOYOU'
    VERSION = '1.0.0'
    PROTOCOL = 'iSCSI'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = 'TOYOU_ACS5000_CI'

    def __init__(self, *args, **kwargs):
        super(Acs5000ISCSIDriver, self).__init__(*args, **kwargs)
        self.protocol = self.PROTOCOL

    @staticmethod
    def get_driver_options():
        return acs5000_common.Acs5000CommonDriver.get_driver_options()

    def validate_connector(self, connector):
        """Check connector for at least one enabled iSCSI protocol."""
        if 'initiator' not in connector:
            LOG.error('The connector does not '
                      'contain the required information.')
            raise exception.InvalidConnectorException(
                missing='initiator')

    @utils.synchronized('Acs5000A-host', external=True)
    def initialize_connection(self, volume, connector):
        LOG.debug('initialize_connection: volume %(vol)s with connector '
                  '%(conn)s', {'vol': volume['id'], 'conn': connector})
        volume_name = acs5000_common.VOLUME_PREFIX + volume['name'][-12:]
        ret = self._cmd.create_lun_map(volume_name,
                                       'WITH_ISCSI',
                                       connector['initiator'])
        if ret['key'] == 303:
            raise exception.VolumeNotFound(volume_id=volume_name)
        elif ret['key'] == 402:
            raise exception.ISCSITargetAttachFailed(volume_id=volume_name)
        else:
            lun_info = ret['arr']
            properties = {}
            properties['target_discovered'] = False
            properties['target_iqns'] = lun_info['iscsi_name']
            properties['target_portals'] = lun_info['portal']
            properties['target_luns'] = lun_info['lun']
            properties['volume_id'] = volume['id']
            properties['auth_method'] = ''
            properties['auth_username'] = ''
            properties['auth_password'] = ''
            properties['discovery_auth_method'] = ''
            properties['discovery_auth_username'] = ''
            properties['discovery_auth_password'] = ''
            return {'driver_volume_type': 'iscsi', 'data': properties}

    @utils.synchronized('Acs5000A-host', external=True)
    def terminate_connection(self, volume, connector, **kwargs):
        LOG.debug('terminate_connection: volume %(vol)s with connector '
                  '%(conn)s', {'vol': volume['id'], 'conn': connector})
        info = {'driver_volume_type': 'iscsi', 'data': {}}
        name = acs5000_common.VOLUME_PREFIX + volume['name'][-12:]
        # -1 means all lun maps
        initiator = '-1'
        if connector and connector['initiator']:
            initiator = connector['initiator']
        self._cmd.delete_lun_map(name,
                                 'WITH_ISCSI',
                                 initiator)
        LOG.debug('leave: terminate_connection: volume %(vol)s with '
                  'connector %(conn)s', {'vol': volume['id'],
                                         'conn': connector})
        return info
