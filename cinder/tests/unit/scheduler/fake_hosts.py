# Copyright 2012 Intel Inc, OpenStack Foundation.
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
Fakes For filters tests.
"""


class FakeHostManager(object):
    """Defines fake hosts.

    host1: free_ram_mb=1024-512-512=0, free_disk_gb=1024-512-512=0
    host2: free_ram_mb=2048-512=1536  free_disk_gb=2048-512=1536
    host3: free_ram_mb=4096-1024=3072  free_disk_gb=4096-1024=3072
    host4: free_ram_mb=8192  free_disk_gb=8192
    """

    def __init__(self):
        self.service_states = {
            'host1': {
                'compute': {'host_memory_free': 1073741824},
            },
            'host2': {
                'compute': {'host_memory_free': 2147483648},
            },
            'host3': {
                'compute': {'host_memory_free': 3221225472},
            },
            'host4': {
                'compute': {'host_memory_free': 999999999},
            },
        }


class FakeHostState(object):
    def __init__(self, host, attribute_dict):
        self.host = host
        for (key, val) in attribute_dict.items():
            setattr(self, key, val)
