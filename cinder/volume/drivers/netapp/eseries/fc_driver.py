# Copyright (c) - 2014, Alex Meade.  All rights reserved.
# Copyright (c) - 2015, Yogesh Kshirsagar.  All Rights Reserved.
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
Volume driver for NetApp E-Series FibreChannel storage systems.
"""

from oslo_log import log as logging

from cinder.volume import driver
from cinder.volume.drivers.netapp.eseries import library
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


class NetAppEseriesFibreChannelDriver(driver.BaseVD,
                                      driver.ManageableVD,
                                      driver.ExtendVD,
                                      driver.TransferVD,
                                      driver.SnapshotVD):
    """NetApp E-Series FibreChannel volume driver."""

    DRIVER_NAME = 'NetApp_FibreChannel_ESeries'

    def __init__(self, *args, **kwargs):
        super(NetAppEseriesFibreChannelDriver, self).__init__(*args, **kwargs)
        na_utils.validate_instantiation(**kwargs)
        self.library = library.NetAppESeriesLibrary(self.DRIVER_NAME,
                                                    'FC', **kwargs)

    def do_setup(self, context):
        self.library.do_setup(context)

    def check_for_setup_error(self):
        self.library.check_for_setup_error()

    def create_volume(self, volume):
        self.library.create_volume(volume)

    def create_volume_from_snapshot(self, volume, snapshot):
        self.library.create_volume_from_snapshot(volume, snapshot)

    def create_cloned_volume(self, volume, src_vref):
        self.library.create_cloned_volume(volume, src_vref)

    def delete_volume(self, volume):
        self.library.delete_volume(volume)

    def create_snapshot(self, snapshot):
        self.library.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        self.library.delete_snapshot(snapshot)

    def get_volume_stats(self, refresh=False):
        return self.library.get_volume_stats(refresh)

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

    @fczm_utils.AddFCZone
    def initialize_connection(self, volume, connector, **kwargs):
        return self.library.initialize_connection_fc(volume, connector)

    @fczm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, **kwargs):
        return self.library.terminate_connection_fc(volume, connector,
                                                    **kwargs)

    def get_pool(self, volume):
        return self.library.get_pool(volume)
