# Copyright 2013 OpenStack Foundation.
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

import os


class HostDriver(object):

    def get_all_block_devices(self):
        """Get the list of all block devices seen in /dev/disk/by-path/."""
        files = []
        dir = "/dev/disk/by-path/"
        if os.path.isdir(dir):
            files = os.listdir(dir)
        devices = []
        for file in files:
            devices.append(dir + file)
        return devices
