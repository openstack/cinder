#    Copyright 2014 Objectif Libre
#    Copyright 2015 Dot Hill Systems Corp.
#    Copyright 2016 Seagate Technology or one of its affiliates
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
from cinder.volume.drivers.dothill import dothill_iscsi
from cinder.volume.drivers.lenovo import lenovo_common


@interface.volumedriver
class LenovoISCSIDriver(dothill_iscsi.DotHillISCSIDriver):
    """OpenStack iSCSI cinder drivers for Lenovo Storage arrays.

    .. code-block:: default

      Version history:
          1.0    - Inheriting from DotHill cinder drivers.
          1.6    - Add management path redundancy and reduce load placed
                   on management controller.
    """

    VERSION = "1.6"

    SUPPORTED = True

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Lenovo_Storage_CI"

    def __init__(self, *args, **kwargs):
        super(LenovoISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(lenovo_common.common_opts)
        self.configuration.append_config_values(lenovo_common.iscsi_opts)
        self.iscsi_ips = self.configuration.lenovo_iscsi_ips

    def _init_common(self):
        return lenovo_common.LenovoCommon(self.configuration)
