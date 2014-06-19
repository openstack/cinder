# Copyright (c) 2013 Huawei Technologies Co., Ltd.
# Copyright (c) 2013 OpenStack Foundation
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
Volume Drivers for Huawei OceanStor HVS storage arrays.
"""

from cinder.volume import driver
from cinder.volume.drivers.huawei.rest_common import HVSCommon
from cinder.zonemanager import utils as fczm_utils


class HuaweiHVSISCSIDriver(driver.ISCSIDriver):
    """ISCSI driver for Huawei OceanStor HVS storage arrays."""

    VERSION = '1.0.0'

    def __init__(self, *args, **kwargs):
        super(HuaweiHVSISCSIDriver, self).__init__(*args, **kwargs)

    def do_setup(self, context):
        """Instantiate common class and log in storage system."""
        self.common = HVSCommon(configuration=self.configuration)

    def check_for_setup_error(self):
        """Check configuration  file."""
        self.common._check_conf_file()
        self.common.login()

    def create_volume(self, volume):
        """Create a volume."""
        self.common.create_volume(volume)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot."""
        self.common.create_volume_from_snapshot(volume, snapshot)

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume."""
        self.common.create_cloned_volume(volume, src_vref)

    def extend_volume(self, volume, new_size):
        """Extend a volume."""
        self.common.extend_volume(volume, new_size)

    def delete_volume(self, volume):
        """Delete a volume."""
        self.common.delete_volume(volume)

    def create_snapshot(self, snapshot):
        """Create a snapshot."""
        self.common.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""
        self.common.delete_snapshot(snapshot)

    def get_volume_stats(self, refresh=False):
        """Get volume stats."""
        data = self.common.update_volume_stats(refresh)
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.__class__.__name__
        data['storage_protocol'] = 'iSCSI'
        data['driver_version'] = self.VERSION
        return data

    def initialize_connection(self, volume, connector):
        """Map a volume to a host."""
        return self.common.initialize_connection_iscsi(volume, connector)

    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate the map."""
        self.common.terminate_connection(volume, connector, **kwargs)

    def create_export(self, context, volume):
        """Export the volume."""
        pass

    def ensure_export(self, context, volume):
        """Synchronously recreate an export for a volume."""
        pass

    def remove_export(self, context, volume):
        """Remove an export for a volume."""
        pass


class HuaweiHVSFCDriver(driver.FibreChannelDriver):
    """FC driver for Huawei OceanStor HVS storage arrays."""

    VERSION = '1.0.0'

    def __init__(self, *args, **kwargs):
        super(HuaweiHVSFCDriver, self).__init__(*args, **kwargs)

    def do_setup(self, context):
        """Instantiate common class and log in storage system."""
        self.common = HVSCommon(configuration=self.configuration)
        self.common.login()

    def check_for_setup_error(self):
        """Check configuration  file."""
        self.common._check_conf_file()

    def create_volume(self, volume):
        """Create a volume."""
        self.common.create_volume(volume)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot."""
        self.common.create_volume_from_snapshot(volume, snapshot)

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume."""
        self.common.create_cloned_volume(volume, src_vref)

    def extend_volume(self, volume, new_size):
        """Extend a volume."""
        self.common.extend_volume(volume, new_size)

    def delete_volume(self, volume):
        """Delete a volume."""
        self.common.delete_volume(volume)

    def create_snapshot(self, snapshot):
        """Create a snapshot."""
        self.common.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""
        self.common.delete_snapshot(snapshot)

    def get_volume_stats(self, refresh=False):
        """Get volume stats."""
        data = self.common.update_volume_stats(refresh)
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.__class__.__name__
        data['storage_protocol'] = 'FC'
        data['driver_version'] = self.VERSION
        return data

    @fczm_utils.AddFCZone
    def initialize_connection(self, volume, connector):
        """Map a volume to a host."""
        return self.common.initialize_connection_fc(volume, connector)

    @fczm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate the map."""
        self.common.terminate_connection(volume, connector, **kwargs)

    def create_export(self, context, volume):
        """Export the volume."""
        pass

    def ensure_export(self, context, volume):
        """Synchronously recreate an export for a volume."""
        pass

    def remove_export(self, context, volume):
        """Remove an export for a volume."""
        pass
