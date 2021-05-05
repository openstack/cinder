# Copyright (c) 2020 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Cinder driver for Dell EMC PowerStore."""

from oslo_config import cfg

from cinder import interface
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.dell_emc.powerstore import adapter
from cinder.volume.drivers.dell_emc.powerstore.options import POWERSTORE_OPTS
from cinder.volume.drivers.san import san


CONF = cfg.CONF
CONF.register_opts(POWERSTORE_OPTS, group=configuration.SHARED_CONF_GROUP)


@interface.volumedriver
class PowerStoreDriver(driver.VolumeDriver):
    """Dell EMC PowerStore Driver.

    .. code-block:: none

      Version history:
        1.0.0 - Initial version
        1.0.1 - Add CHAP support
        1.0.2 - Fix iSCSI targets not being returned from the REST API call if
                targets are used for multiple purposes
                (iSCSI target, Replication target, etc.)
    """

    VERSION = "1.0.2"
    VENDOR = "Dell EMC"

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "DellEMC_PowerStore_CI"

    def __init__(self, *args, **kwargs):
        super(PowerStoreDriver, self).__init__(*args, **kwargs)

        self.active_backend_id = kwargs.get("active_backend_id")
        self.adapter = None
        self.configuration.append_config_values(san.san_opts)
        self.configuration.append_config_values(POWERSTORE_OPTS)

    @staticmethod
    def get_driver_options():
        return POWERSTORE_OPTS

    def do_setup(self, context):
        storage_protocol = self.configuration.safe_get("storage_protocol")
        if (
                storage_protocol and
                storage_protocol.lower() == adapter.PROTOCOL_FC.lower()
        ):
            self.adapter = adapter.FibreChannelAdapter(self.active_backend_id,
                                                       self.configuration)
        else:
            self.adapter = adapter.iSCSIAdapter(self.active_backend_id,
                                                self.configuration)
        self.adapter.do_setup()

    def check_for_setup_error(self):
        self.adapter.check_for_setup_error()

    def create_volume(self, volume):
        return self.adapter.create_volume(volume)

    def delete_volume(self, volume):
        return self.adapter.delete_volume(volume)

    def extend_volume(self, volume, new_size):
        return self.adapter.extend_volume(volume, new_size)

    def create_snapshot(self, snapshot):
        return self.adapter.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        return self.adapter.delete_snapshot(snapshot)

    def create_cloned_volume(self, volume, src_vref):
        return self.adapter.create_cloned_volume(volume, src_vref)

    def create_volume_from_snapshot(self, volume, snapshot):
        return self.adapter.create_volume_from_snapshot(volume, snapshot)

    def initialize_connection(self, volume, connector, **kwargs):
        return self.adapter.initialize_connection(volume, connector, **kwargs)

    def terminate_connection(self, volume, connector, **kwargs):
        return self.adapter.terminate_connection(volume, connector, **kwargs)

    def revert_to_snapshot(self, context, volume, snapshot):
        return self.adapter.revert_to_snapshot(volume, snapshot)

    def _update_volume_stats(self):
        stats = self.adapter.update_volume_stats()
        stats["driver_version"] = self.VERSION
        stats["vendor_name"] = self.VENDOR
        self._stats = stats

    def create_export(self, context, volume, connector):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass
