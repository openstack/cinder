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


from cinder.openstack.common import log as logging
from cinder.volume.targets.tgt import TgtAdm


LOG = logging.getLogger(__name__)


class ISERTgtAdm(TgtAdm):
    VERSION = '0.2'

    VOLUME_CONF = """
                <target %s>
                    driver iser
                    backing-store %s
                    write_cache %s
                </target>
                  """
    VOLUME_CONF_WITH_CHAP_AUTH = """
                                <target %s>
                                    driver iser
                                    backing-store %s
                                    %s
                                    write_cache %s
                                </target>
                                 """

    def __init__(self, *args, **kwargs):
        super(ISERTgtAdm, self).__init__(*args, **kwargs)
        self.volumes_dir = self.configuration.safe_get('volumes_dir')
        self.protocol = 'iSER'

        # backwards compatibility mess
        self.configuration.num_volume_device_scan_tries = \
            self.configuration.num_iser_scan_tries
        self.configuration.iscsi_num_targets = \
            self.configuration.iser_num_targets
        self.configuration.iscsi_target_prefix = \
            self.configuration.iser_target_prefix
        self.configuration.iscsi_ip_address = \
            self.configuration.iser_ip_address
        self.configuration.iscsi_port = self.configuration.iser_port

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.
        The iser driver returns a driver_volume_type of 'iser'.
        The format of the driver data is defined in _get_iscsi_properties.
        Example return value::
            {
                'driver_volume_type': 'iser'
                'data': {
                    'target_discovered': True,
                    'target_iqn':
                    'iqn.2010-10.org.iser.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'volume_id': 1,
                }
            }
        """
        iser_properties = self._get_iscsi_properties(volume)
        return {
            'driver_volume_type': 'iser',
            'data': iser_properties
        }
