#    Copyright 2014 Objectif Libre
#    Copyright 2015 Dot Hill Systems Corp.
#    Copyright 2016-2019 Seagate Technology or one of its affiliates
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

from cinder import interface
import cinder.volume.drivers.san.hp.hpmsa_common as hpmsa_common
import cinder.volume.drivers.stx.iscsi as iscsi


@interface.volumedriver
class HPMSAISCSIDriver(iscsi.STXISCSIDriver):
    """OpenStack iSCSI cinder drivers for HPMSA arrays.

    .. code-block:: default

      Version history:
          1.0    - Inheriting from DotHill cinder drivers.
          1.6    - Add management path redundancy and reduce load placed
                   on management controller.
          2.0    - DotHill driver renamed to Seagate (STX)
    """

    VERSION = "2.0"

    CI_WIKI_NAME = "HPMSA_CI"

    SUPPORTED = True

    def __init__(self, *args, **kwargs):
        super(HPMSAISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(hpmsa_common.common_opts)
        self.configuration.append_config_values(hpmsa_common.iscsi_opts)
        self.iscsi_ips = self.configuration.hpmsa_iscsi_ips

    @staticmethod
    def get_driver_options():
        return (hpmsa_common.HPMSACommon.get_driver_options() +
                hpmsa_common.iscsi_opts)

    def _init_common(self):
        return hpmsa_common.HPMSACommon(self.configuration)
