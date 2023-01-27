# Copyright (c) 2023 NetApp, Inc. All rights reserved.
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
Volume driver for NetApp Data ONTAP NVMe storage systems.
"""

from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.netapp.dataontap import nvme_library
from cinder.volume.drivers.netapp import options as na_opts


@interface.volumedriver
class NetAppCmodeNVMeDriver(driver.BaseVD):
    """NetApp C-mode NVMe volume driver.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver

    """

    VERSION = "1.0.0"

    DRIVER_NAME = 'NetApp_NVMe_Cluster_direct'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "NetApp_CI"

    def __init__(self, *args, **kwargs):
        super(NetAppCmodeNVMeDriver, self).__init__(*args, **kwargs)
        self.library = nvme_library.NetAppNVMeStorageLibrary(
            self.DRIVER_NAME, 'NVMe', **kwargs)

    @staticmethod
    def get_driver_options():
        return na_opts.netapp_cluster_opts

    def do_setup(self, context):
        self.library.do_setup(context)

    def check_for_setup_error(self):
        self.library.check_for_setup_error()

    def create_volume(self, volume):
        return self.library.create_volume(volume)

    def create_volume_from_snapshot(self, volume, snapshot):
        return self.library.create_volume_from_snapshot(volume, snapshot)

    def create_cloned_volume(self, volume, src_vref):
        return self.library.create_cloned_volume(volume, src_vref)

    def delete_volume(self, volume):
        self.library.delete_volume(volume)

    def create_snapshot(self, snapshot):
        self.library.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        self.library.delete_snapshot(snapshot)

    def get_volume_stats(self, refresh=False):
        return self.library.get_volume_stats(refresh,
                                             self.get_filter_function(),
                                             self.get_goodness_function())

    def get_default_filter_function(self):
        return self.library.get_default_filter_function()

    def get_default_goodness_function(self):
        return self.library.get_default_goodness_function()

    def extend_volume(self, volume, new_size):
        self.library.extend_volume(volume, new_size)

    def ensure_export(self, context, volume):
        return self.library.ensure_export(context, volume)

    def create_export(self, context, volume, connector):
        return self.library.create_export(context, volume)

    def remove_export(self, context, volume):
        self.library.remove_export(context, volume)

    def initialize_connection(self, volume, connector):
        conn_info = self.library.initialize_connection(volume, connector)
        return conn_info

    def terminate_connection(self, volume, connector, **kwargs):
        conn_info = self.library.terminate_connection(volume, connector,
                                                      **kwargs)
        return conn_info

    def get_pool(self, volume):
        return self.library.get_pool(volume)
