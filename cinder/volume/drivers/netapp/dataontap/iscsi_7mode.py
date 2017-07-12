# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2016 Mike Rooney. All rights reserved.
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
Volume driver for NetApp Data ONTAP (7-mode) iSCSI storage systems.
"""

from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.netapp.dataontap import block_7mode


@interface.volumedriver
class NetApp7modeISCSIDriver(driver.BaseVD,
                             driver.ManageableVD):
    """NetApp 7-mode iSCSI volume driver."""

    DRIVER_NAME = 'NetApp_iSCSI_7mode_direct'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "NetApp_CI"
    VERSION = block_7mode.NetAppBlockStorage7modeLibrary.VERSION

    def __init__(self, *args, **kwargs):
        super(NetApp7modeISCSIDriver, self).__init__(*args, **kwargs)
        self.library = block_7mode.NetAppBlockStorage7modeLibrary(
            self.DRIVER_NAME, 'iSCSI', **kwargs)

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

    def manage_existing(self, volume, existing_ref):
        return self.library.manage_existing(volume, existing_ref)

    def manage_existing_get_size(self, volume, existing_ref):
        return self.library.manage_existing_get_size(volume, existing_ref)

    def unmanage(self, volume):
        return self.library.unmanage(volume)

    def initialize_connection(self, volume, connector):
        return self.library.initialize_connection_iscsi(volume, connector)

    def terminate_connection(self, volume, connector, **kwargs):
        return self.library.terminate_connection_iscsi(volume, connector,
                                                       **kwargs)

    def get_pool(self, volume):
        return self.library.get_pool(volume)

    def create_consistencygroup(self, context, group):
        return self.library.create_consistencygroup(group)

    def delete_consistencygroup(self, context, group, volumes):
        return self.library.delete_consistencygroup(group, volumes)

    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):
        return self.library.update_consistencygroup(group, add_volumes=None,
                                                    remove_volumes=None)

    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        return self.library.create_cgsnapshot(cgsnapshot, snapshots)

    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        return self.library.delete_cgsnapshot(cgsnapshot, snapshots)

    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None,
                                         source_cg=None, source_vols=None):
        return self.library.create_consistencygroup_from_src(
            group, volumes, cgsnapshot=cgsnapshot, snapshots=snapshots,
            source_cg=source_cg, source_vols=source_vols)

    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        raise NotImplementedError()
