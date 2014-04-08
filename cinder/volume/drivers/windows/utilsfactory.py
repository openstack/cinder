# Copyright 2014 Cloudbase Solutions Srl
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

from cinder.openstack.common import log as logging
from cinder.volume.drivers.windows import vhdutils
from cinder.volume.drivers.windows import vhdutilsv2
from cinder.volume.drivers.windows import windows_utils

LOG = logging.getLogger(__name__)


def _get_class(v1_class, v2_class):
    # V2 classes are supported starting from Hyper-V Server 2012 and
    # Windows Server 2012 (kernel version 6.2)
    if not windows_utils.WindowsUtils().check_min_windows_version(6, 2):
        cls = v2_class
    else:
        cls = v1_class
    LOG.debug("Loading class: %(module_name)s.%(class_name)s",
              {'module_name': cls.__module__, 'class_name': cls.__name__})
    return cls


def get_vhdutils():
    return _get_class(vhdutils.VHDUtils, vhdutilsv2.VHDUtilsV2)()
