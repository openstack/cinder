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
from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.dell_emc.powerstore import adapter
from cinder.volume.drivers.dell_emc.powerstore import options
from cinder.volume.drivers.san import san
from cinder.volume import manager


POWERSTORE_OPTS = options.POWERSTORE_OPTS
CONF = cfg.CONF
CONF.register_opts(POWERSTORE_OPTS, group=configuration.SHARED_CONF_GROUP)
LOG = logging.getLogger(__name__)
POWERSTORE_PP_KEY = "powerstore:protection_policy"


@interface.volumedriver
class PowerStoreDriver(driver.VolumeDriver):
    """Dell EMC PowerStore Driver.

    .. code-block:: none

      Version history:
        1.0.0 - Initial version
        1.0.1 - Add CHAP support
        1.1.0 - Add volume replication v2.1 support
        1.1.1 - Add Consistency Groups support
        1.1.2 - Fix iSCSI targets not being returned from the REST API call if
                targets are used for multiple purposes
                (iSCSI target, Replication target, etc.)
    """

    VERSION = "1.1.2"
    VENDOR = "Dell EMC"

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "DellEMC_PowerStore_CI"

    def __init__(self, *args, **kwargs):
        super(PowerStoreDriver, self).__init__(*args, **kwargs)

        self.active_backend_id = kwargs.get("active_backend_id")
        self.adapters = {}
        self.configuration.append_config_values(san.san_opts)
        self.configuration.append_config_values(POWERSTORE_OPTS)
        self.replication_configured = False
        self.replication_devices = None

    def _init_vendor_properties(self):
        properties = {}
        self._set_property(
            properties,
            POWERSTORE_PP_KEY,
            "PowerStore Protection Policy.",
            _("Specifies the PowerStore Protection Policy for a "
              "volume type. Protection Policy is assigned to a volume during "
              "creation."),
            "string"
        )
        return properties, "powerstore"

    @staticmethod
    def get_driver_options():
        return POWERSTORE_OPTS

    def do_setup(self, context):
        if not self.active_backend_id:
            self.active_backend_id = manager.VolumeManager.FAILBACK_SENTINEL
        storage_protocol = self.configuration.safe_get("storage_protocol")
        if (
                storage_protocol and
                storage_protocol.lower() == adapter.PROTOCOL_FC.lower()
        ):
            adapter_class = adapter.FibreChannelAdapter
        else:
            adapter_class = adapter.iSCSIAdapter
        self.replication_devices = (
            self.configuration.safe_get("replication_device") or []
        )
        self.adapters[manager.VolumeManager.FAILBACK_SENTINEL] = adapter_class(
            **self._get_device_configuration()
        )
        for index, device in enumerate(self.replication_devices):
            self.adapters[device["backend_id"]] = adapter_class(
                **self._get_device_configuration(is_primary=False,
                                                 device_index=index)
            )

    def check_for_setup_error(self):
        if len(self.replication_devices) > 1:
            msg = _("PowerStore driver does not support more than one "
                    "replication device.")
            raise exception.InvalidInput(reason=msg)
        self.replication_configured = True
        for adapter in self.adapters.values():
            adapter.check_for_setup_error()

    def create_volume(self, volume):
        return self.adapter.create_volume(volume)

    def delete_volume(self, volume):
        if volume.is_replicated():
            self.adapter.teardown_volume_replication(volume)
            self.adapter.delete_volume(volume)
            if not self.is_failed_over:
                for backend_id in self.failover_choices:
                    self.adapters.get(backend_id).delete_volume(volume)
        else:
            self.adapter.delete_volume(volume)

    def extend_volume(self, volume, new_size):
        return self.adapter.extend_volume(volume, new_size)

    def create_snapshot(self, snapshot):
        return self.adapter.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        self.adapter.delete_snapshot(snapshot)
        if snapshot.volume.is_replicated() and not self.is_failed_over:
            for backend_id in self.failover_choices:
                self.adapters.get(backend_id).delete_snapshot(snapshot)

    def create_cloned_volume(self, volume, src_vref):
        return self.adapter.create_volume_from_source(volume, src_vref)

    def create_volume_from_snapshot(self, volume, snapshot):
        return self.adapter.create_volume_from_source(volume, snapshot)

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
        stats["replication_enabled"] = self.replication_enabled
        stats["replication_targets"] = self.replication_targets
        self._stats = stats

    def create_export(self, context, volume, connector):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        if secondary_id not in self.failover_choices:
            msg = (_("Target %(target)s is not a valid choice. "
                     "Valid choices: %(choices)s.") %
                   {"target": secondary_id,
                    "choices": ', '.join(self.failover_choices)})
            LOG.error(msg)
            raise exception.InvalidReplicationTarget(reason=msg)
        is_failback = secondary_id == manager.VolumeManager.FAILBACK_SENTINEL
        self.active_backend_id = secondary_id
        volumes_updates, groups_updates = self.adapter.failover_host(
            volumes,
            groups,
            is_failback
        )
        return secondary_id, volumes_updates, groups_updates

    def create_group(self, context, group):
        return self.adapter.create_group(group)

    def delete_group(self, context, group, volumes):
        return self.adapter.delete_group(group)

    def update_group(self, context, group,
                     add_volumes=None, remove_volumes=None):
        return self.adapter.update_group(group, add_volumes, remove_volumes)

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        return self.adapter.create_group_snapshot(group_snapshot)

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        return self.adapter.delete_group_snapshot(group_snapshot)

    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        source = group_snapshot or source_group
        return self.adapter.create_group_from_source(group,
                                                     volumes,
                                                     source,
                                                     snapshots,
                                                     source_vols)

    @property
    def adapter(self):
        return self.adapters.get(self.active_backend_id)

    @property
    def failover_choices(self):
        return (
            set(self.adapters.keys()).difference({self.active_backend_id})
        )

    @property
    def is_failed_over(self):
        return (
            self.active_backend_id != manager.VolumeManager.FAILBACK_SENTINEL
        )

    @property
    def replication_enabled(self):
        return self.replication_configured and not self.is_failed_over

    @property
    def replication_targets(self):
        if self.replication_enabled:
            return list(self.adapters.keys())
        return []

    def _get_device_configuration(self, is_primary=True, device_index=0):
        conf = {}
        if is_primary:
            get_value = self.configuration.safe_get
            backend_id = manager.VolumeManager.FAILBACK_SENTINEL
        else:
            get_value = self.replication_devices[device_index].get
            backend_id = get_value("backend_id")
        conf["backend_id"] = backend_id
        conf["backend_name"] = (
            self.configuration.safe_get("volume_backend_name") or "powerstore"
        )
        conf["ports"] = get_value(options.POWERSTORE_PORTS) or []
        conf["rest_ip"] = get_value("san_ip")
        conf["rest_username"] = get_value("san_login")
        conf["rest_password"] = get_value("san_password")
        conf["verify_certificate"] = get_value("driver_ssl_cert_verify")
        conf["certificate_path"] = get_value("driver_ssl_cert_path")
        return conf
