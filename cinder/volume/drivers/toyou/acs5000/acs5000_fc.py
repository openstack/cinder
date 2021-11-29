# Copyright 2021 toyou Corp.
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
acs5000 FC driver
"""

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume.drivers.toyou.acs5000 import acs5000_common
from cinder.zonemanager import utils as zone_utils

LOG = logging.getLogger(__name__)


@interface.volumedriver
class Acs5000FCDriver(acs5000_common.Acs5000CommonDriver):
    """TOYOU ACS5000 storage FC volume driver.

    .. code-block:: none

      Version history:
          1.0.0 - Initial driver

    """

    VENDOR = 'TOYOU'
    VERSION = '1.0.0'
    PROTOCOL = 'FC'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = 'TOYOU_ACS5000_CI'

    def __init__(self, *args, **kwargs):
        super(Acs5000FCDriver, self).__init__(*args, **kwargs)
        self.protocol = self.PROTOCOL

    @staticmethod
    def get_driver_options():
        return acs5000_common.Acs5000CommonDriver.get_driver_options()

    def _get_connected_wwpns(self):
        fc_ports = self._cmd.ls_fc()
        connected_wwpns = []
        for port in fc_ports:
            if 'wwpn' in port:
                connected_wwpns.append(port['wwpn'])
            elif 'WWPN' in port:
                connected_wwpns.append(port['WWPN'])
        return connected_wwpns

    def validate_connector(self, connector):
        """Check connector for at least one enabled FC protocol."""
        if 'wwpns' not in connector:
            LOG.error('The connector does not '
                      'contain the required information.')
            raise exception.InvalidConnectorException(
                missing='wwpns')

    @utils.synchronized('acs5000A-host', external=True)
    def initialize_connection(self, volume, connector):
        LOG.debug('enter: initialize_connection: volume '
                  '%(vol)s with connector %(conn)s',
                  {'vol': volume.id, 'conn': connector})
        volume_name = self._convert_name(volume.name)
        ret = self._cmd.create_lun_map(volume_name,
                                       self.protocol,
                                       connector['wwpns'])
        if ret['key'] == 0:
            if 'lun' in ret['arr']:
                lun_id = int(ret['arr']['lun'])
            else:
                msg = (_('_create_fc_lun: Lun id did not find '
                         'when volume %s create lun map.') % volume['id'])
                raise exception.VolumeBackendAPIException(data=msg)

            target_wwpns = self._get_connected_wwpns()
            if len(target_wwpns) == 0:
                if self._check_multi_attached(volume, connector) < 1:
                    self._cmd.delete_lun_map(volume_name,
                                             self.protocol,
                                             connector['wwpns'])
                msg = (_('_create_fc_lun: Did not find '
                         'available fc wwpns when volume %s '
                         'create lun map.') % volume['id'])
                raise exception.VolumeBackendAPIException(data=msg)

            initiator_target = {}
            for initiator_wwpn in connector['wwpns']:
                initiator_target[str(initiator_wwpn)] = target_wwpns
            properties = {'driver_volume_type': 'fibre_channel',
                          'data': {'target_wwn': target_wwpns,
                                   'target_discovered': False,
                                   'target_lun': lun_id,
                                   'volume_id': volume['id']}}
            properties['data']['initiator_target_map'] = initiator_target
        elif ret['key'] == 303:
            raise exception.VolumeNotFound(volume_id=volume_name)
        else:
            msg = (_('failed to map the volume %(vol)s to '
                     'connector %(conn)s.') %
                   {'vol': volume['id'], 'conn': connector})
            raise exception.VolumeBackendAPIException(data=msg)

        zone_utils.add_fc_zone(properties)
        LOG.debug('leave: initialize_connection: volume '
                  '%(vol)s with connector %(conn)s',
                  {'vol': volume.id, 'conn': connector})
        return properties

    @utils.synchronized('acs5000A-host', external=True)
    def terminate_connection(self, volume, connector, **kwargs):
        LOG.debug('enter: terminate_connection: volume '
                  '%(vol)s with connector %(conn)s',
                  {'vol': volume.id, 'conn': connector})
        volume_name = self._convert_name(volume.name)
        properties = {'driver_volume_type': 'fibre_channel',
                      'data': {}}
        initiator_wwpns = []
        target_wwpns = []
        if connector and 'wwpns' in connector:
            initiator_wwpns = connector['wwpns']
            target_wwpns = self._get_connected_wwpns()
            if len(target_wwpns) == 0:
                target_wwpns = []
                LOG.warning('terminate_connection: Did not find '
                            'available fc wwpns when volume %s '
                            'delete lun map.', volume.id)

        initiator_target = {}
        for i_wwpn in initiator_wwpns:
            initiator_target[str(i_wwpn)] = target_wwpns
        properties['data'] = {'initiator_target_map': initiator_target}
        if self._check_multi_attached(volume, connector) < 2:
            if not initiator_wwpns:
                # -1 means all lun maps of this volume
                initiator_wwpns = -1
            self._cmd.delete_lun_map(volume_name,
                                     self.protocol,
                                     initiator_wwpns)
        else:
            LOG.warning('volume %s has been mapped to multi VMs, and these '
                        'VMs belong to the same host. The mapping '
                        'cancellation request is aborted.', volume.id)
        zone_utils.remove_fc_zone(properties)
        LOG.debug('leave: terminate_connection: volume '
                  '%(vol)s with connector %(conn)s',
                  {'vol': volume.id, 'conn': connector})
        return properties
