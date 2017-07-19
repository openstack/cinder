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
"""Fibre channel Cinder volume driver for FalconStor FSS storage system.

This driver requires FSS-8.00-8865 or later.
"""

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder import interface
import cinder.volume.driver
from cinder.volume.drivers.falconstor import fss_common
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


@interface.volumedriver
class FSSFCDriver(fss_common.FalconstorBaseDriver,
                  cinder.volume.driver.FibreChannelDriver):
    """Implements commands for FalconStor FSS FC management.

    To enable the driver add the following line to the cinder configuration:
        volume_driver=cinder.volume.drivers.falconstor.fc.FSSFCDriver

    Version history:
        1.0.0 - Initial driver

    """

    VERSION = '1.0.0'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "FalconStor_CI"

    # TODO(smcginnis) Remove driver in the Queens release if CI issues
    # are not addressed
    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        super(FSSFCDriver, self).__init__(*args, **kwargs)
        self.gateway_fc_wwns = []
        self._storage_protocol = "FC"
        self._backend_name = (
            self.configuration.safe_get('volume_backend_name') or
            self.__class__.__name__)
        self._lookup_service = fczm_utils.create_lookup_service()

    def do_setup(self, context):
        """Any initialization the driver does while starting."""
        super(FSSFCDriver, self).do_setup(context)
        self.gateway_fc_wwns = self.proxy.list_fc_target_wwpn()

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        super(FSSFCDriver, self).check_for_setup_error()
        if len(self.gateway_fc_wwns) == 0:
            msg = _('No FC targets found')
            raise exception.InvalidHost(reason=msg)

    def validate_connector(self, connector):
        """Check connector for at least one enabled FC protocol."""
        if 'FC' == self._storage_protocol and 'wwpns' not in connector:
            LOG.error('The connector does not contain the required '
                      'information.')
            raise exception.InvalidConnectorException(missing='wwpns')

    @fczm_utils.add_fc_zone
    def initialize_connection(self, volume, connector):
        fss_hosts = []
        fss_hosts.append(self.configuration.san_ip)
        target_info = self.proxy.fc_initialize_connection(volume, connector,
                                                          fss_hosts)
        init_targ_map = self._build_initiator_target_map(
            target_info['available_initiator'])

        fc_info = {'driver_volume_type': 'fibre_channel',
                   'data': {'target_lun': int(target_info['lun']),
                            'target_discovered': True,
                            'target_wwn': self.gateway_fc_wwns,
                            'initiator_target_map': init_targ_map,
                            'volume_id': volume['id'],
                            }
                   }
        return fc_info

    def _build_initiator_target_map(self, initiator_wwns):
        """Build the target_wwns and the initiator target map."""
        init_targ_map = dict.fromkeys(initiator_wwns, self.gateway_fc_wwns)
        return init_targ_map

    @fczm_utils.remove_fc_zone
    def terminate_connection(self, volume, connector, **kwargs):
        host_id = self.proxy.fc_terminate_connection(volume, connector)
        fc_info = {"driver_volume_type": "fibre_channel", "data": {}}
        if self.proxy._check_fc_host_devices_empty(host_id):
            available_initiator, fc_initiators_info = (
                self.proxy._get_fc_client_initiators(connector))
            init_targ_map = self._build_initiator_target_map(
                available_initiator)
            fc_info["data"] = {"target_wwn": self.gateway_fc_wwns,
                               "initiator_target_map": init_targ_map}
        return fc_info
