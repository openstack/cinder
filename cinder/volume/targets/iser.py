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

from oslo_log import log as logging

from cinder.i18n import _LW
from cinder.volume.targets import tgt


LOG = logging.getLogger(__name__)


class ISERTgtAdm(tgt.TgtAdm):
    VERSION = '0.2'

    def __init__(self, *args, **kwargs):
        super(ISERTgtAdm, self).__init__(*args, **kwargs)

        LOG.warning(_LW('ISERTgtAdm is deprecated, you should '
                        'now just use LVMVolumeDriver and specify '
                        'iscsi_helper for the target driver you '
                        'wish to use. In order to enable iser, please '
                        'set iscsi_protocol=iser with lioadm or tgtadm '
                        'target helpers.'))

        self.volumes_dir = self.configuration.safe_get('volumes_dir')
        self.iscsi_protocol = 'iser'
        self.protocol = 'iSER'

        # backwards compatibility mess
        self.configuration.num_volume_device_scan_tries = \
            self.configuration.num_iser_scan_tries
        self.configuration.iscsi_target_prefix = \
            self.configuration.iser_target_prefix
        self.configuration.iscsi_ip_address = \
            self.configuration.iser_ip_address
        self.configuration.iscsi_port = self.configuration.iser_port
