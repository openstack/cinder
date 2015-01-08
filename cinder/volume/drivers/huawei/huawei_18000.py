# Copyright (c) 2013 - 2014 Huawei Technologies Co., Ltd.
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
Volume Drivers for Huawei OceanStor 18000 storage arrays.
"""

from cinder.volume import driver
from cinder.volume.drivers.huawei import rest_common
from cinder.zonemanager import utils as fczm_utils


class Huawei18000ISCSIDriver(driver.ISCSIDriver):
    """ISCSI driver for Huawei OceanStor 18000 storage arrays.

    Version history:
        1.0.0 - Initial driver
        1.1.0 - Provide Huawei OceanStor 18000 storage volume driver.
    """

    VERSION = "1.1.0"

    def __init__(self, *args, **kwargs):
        super(Huawei18000ISCSIDriver, self).__init__(*args, **kwargs)

    def do_setup(self, context):
        """Instantiate common class and log in storage system."""
        self.common = rest_common.RestCommon(configuration=self.configuration)
        return self.common.login()

    def check_for_setup_error(self):
        """Check configuration file."""
        return self.common._check_conf_file()

    def create_volume(self, volume):
        """Create a volume."""
        lun_info = self.common.create_volume(volume)
        return {'provider_location': lun_info['ID'],
                'lun_info': lun_info}

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot."""
        lun_info = self.common.create_volume_from_snapshot(volume, snapshot)
        return {'provider_location': lun_info['ID'],
                'lun_info': lun_info}

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume."""
        lun_info = self.common.create_cloned_volume(volume, src_vref)
        return {'provider_location': lun_info['ID'],
                'lun_info': lun_info}

    def extend_volume(self, volume, new_size):
        """Extend a volume."""
        return self.common.extend_volume(volume, new_size)

    def delete_volume(self, volume):
        """Delete a volume."""
        return self.common.delete_volume(volume)

    def create_snapshot(self, snapshot):
        """Create a snapshot."""
        lun_info = self.common.create_snapshot(snapshot)
        return {'provider_location': lun_info['ID'],
                'lun_info': lun_info}

    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""
        return self.common.delete_snapshot(snapshot)

    def get_volume_stats(self, refresh=False):
        """Get volume stats."""
        data = self.common.update_volume_stats()
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
        self.common.terminate_connection_iscsi(volume, connector)

    def create_export(self, context, volume):
        """Export the volume."""
        pass

    def ensure_export(self, context, volume):
        """Synchronously recreate an export for a volume."""
        pass

    def remove_export(self, context, volume):
        """Remove an export for a volume."""
        pass


class Huawei18000FCDriver(driver.FibreChannelDriver):
    """FC driver for Huawei OceanStor 18000 storage arrays.

    Version history:
        1.0.0 - Initial driver
        1.1.0 - Provide Huawei OceanStor 18000 storage volume driver.
    """

    VERSION = "1.1.0"

    def __init__(self, *args, **kwargs):
        super(Huawei18000FCDriver, self).__init__(*args, **kwargs)

    def do_setup(self, context):
        """Instantiate common class and log in storage system."""
        self.common = rest_common.RestCommon(configuration=self.configuration)
        return self.common.login()

    def check_for_setup_error(self):
        """Check configuration file."""
        return self.common._check_conf_file()

    def create_volume(self, volume):
        """Create a volume."""
        lun_info = self.common.create_volume(volume)
        return {'provider_location': lun_info['ID'],
                'lun_info': lun_info}

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot."""
        lun_info = self.common.create_volume_from_snapshot(volume, snapshot)
        return {'provider_location': lun_info['ID'],
                'lun_info': lun_info}

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume."""
        lun_info = self.common.create_cloned_volume(volume, src_vref)
        return {'provider_location': lun_info['ID'],
                'lun_info': lun_info}

    def extend_volume(self, volume, new_size):
        """Extend a volume."""
        return self.common.extend_volume(volume, new_size)

    def delete_volume(self, volume):
        """Delete a volume."""
        return self.common.delete_volume(volume)

    def create_snapshot(self, snapshot):
        """Create a snapshot."""
        lun_info = self.common.create_snapshot(snapshot)
        return {'provider_location': lun_info['ID'],
                'lun_info': lun_info}

    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""
        return self.common.delete_snapshot(snapshot)

    def get_volume_stats(self, refresh=False):
        """Get volume stats."""
        data = self.common.update_volume_stats()
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
        return self.common.terminate_connection_fc(volume, connector)

    def create_export(self, context, volume):
        """Export the volume."""
        pass

    def ensure_export(self, context, volume):
        """Synchronously recreate an export for a volume."""
        pass

    def remove_export(self, context, volume):
        """Remove an export for a volume."""
        pass
