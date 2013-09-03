# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Huawei Technologies Co., Ltd.
# Copyright (c) 2012 OpenStack LLC.
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

from cinder.volume.drivers.huawei import huawei_t
from cinder.volume.drivers.huawei import ssh_common


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
