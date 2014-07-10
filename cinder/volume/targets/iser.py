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
                </target>
                  """
    VOLUME_CONF_WITH_CHAP_AUTH = """
                                <target %s>
                                    driver iser
                                    backing-store %s
                                    %s
                                </target>
                                 """

    def __init__(self, *args, **kwargs):
        super(ISERTgtAdm, self).__init__(*args, **kwargs)
        self.volumes_dir = self.configuration.safe_get('volumes_dir')
        self.protocol = 'iSER'

        # backward compatability mess
        self.configuration.num_volume_device_scan_tries = \
            self.configuration.num_iser_scan_tries
        self.configuration.iscsi_num_targets = \
            self.configuration.iser_num_targets
        self.configuration.iscsi_target_prefix = \
            self.configuration.iser_target_prefix
        self.configuration.iscsi_ip_address = \
            self.configuration.iser_ip_address
        self.configuration.iscsi_port = self.configuration.iser_port
