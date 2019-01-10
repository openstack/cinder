# Copyright (c) 2016 - 2019 Dell Inc. or its subsidiaries.
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

import random

from oslo_log import log as logging
from oslo_utils import excutils

from cinder import exception
from cinder.volume.drivers.dell_emc.unity import adapter as unity_adapter

LOG = logging.getLogger(__name__)


class ReplicationDevice(object):
    def __init__(self, conf_dict, driver):
        """Constructs a replication device from driver configuration.

        :param conf_dict: the conf of one replication device entry. It's a
            dict with content like
            `{backend_id: vendor-id-1, key-1: val-1, ...}`
        :param driver: the backend driver.
        """
        driver_conf = driver.configuration

        self.backend_id = conf_dict.get('backend_id')
        self.san_ip = conf_dict.get('san_ip', None)
        if (self.backend_id is None or not self.backend_id.strip()
                or self.san_ip is None or not self.san_ip.strip()):
            LOG.error('No backend_id or san_ip in %(conf)s of '
                      '%(group)s.replication_device',
                      conf=conf_dict, group=driver_conf.config_group)
            raise exception.InvalidConfigurationValue(
                option='%s.replication_device' % driver_conf.config_group,
                value=driver_conf.replication_device)

        # Use the driver settings if not configured in replication_device.
        self.san_login = conf_dict.get('san_login', driver_conf.san_login)
        self.san_password = conf_dict.get('san_password',
                                          driver_conf.san_password)

        # Max time (in minute) out of sync is a setting for replication.
        # It means maximum time to wait before syncing the source and
        # destination. `0` means it is a sync replication. Default is `60`.
        try:
            self.max_time_out_of_sync = int(
                conf_dict.get('max_time_out_of_sync', 60))
        except ValueError:
            LOG.error('max_time_out_of_sync is not a number, %(conf)s of '
                      '%(group)s.replication_device',
                      conf=conf_dict, group=driver_conf.config_group)
            raise exception.InvalidConfigurationValue(
                option='%s.replication_device' % driver_conf.config_group,
                value=driver_conf.replication_device)
        if self.max_time_out_of_sync < 0:
            LOG.error('max_time_out_of_sync should be greater than 0, '
                      '%(conf)s of %(group)s.replication_device',
                      conf=conf_dict, group=driver_conf.config_group)
            raise exception.InvalidConfigurationValue(
                option='%s.replication_device' % driver_conf.config_group,
                value=driver_conf.replication_device)

        self.driver = driver
        self._adapter = init_adapter(driver.get_version(), driver.protocol)
        self._dst_pool = None
        self._serial_number = None

    @property
    def device_conf(self):
        conf = self.driver.configuration
        conf.san_ip = self.san_ip
        conf.san_login = self.san_login
        conf.san_password = self.san_password
        return conf

    def setup_adapter(self):
        if not self._adapter.is_setup:
            try:
                self._adapter.do_setup(self.driver, self.device_conf)
            except exception.CinderException:
                with excutils.save_and_reraise_exception():
                    LOG.error('replication_device configured but its adapter '
                              'setup failed: %s', self.backend_id)

    @property
    def adapter(self):
        self.setup_adapter()
        return self._adapter

    @property
    def destination_pool(self):
        if self._dst_pool is None:
            LOG.debug('getting destination pool for replication device: %s',
                      self.backend_id)
            pools_dict = self.adapter.storage_pools_map
            pool_name = random.choice(list(pools_dict))
            LOG.debug('got destination pool for replication device: %s, '
                      'pool: %s', self.backend_id, pool_name)
            self._dst_pool = pools_dict[pool_name]

        return self._dst_pool


def init_adapter(version, protocol):
    if protocol == unity_adapter.PROTOCOL_FC:
        return unity_adapter.FCAdapter(version)
    return unity_adapter.ISCSIAdapter(version)


DEFAULT_ADAPTER_NAME = 'default'


class ReplicationManager(object):
    def __init__(self):
        self.is_replication_configured = False
        self.default_conf = None
        self.default_device = None
        self.replication_devices = None
        self.active_backend_id = None

    def do_setup(self, driver):
        self.default_conf = driver.configuration

        self.replication_devices = self.parse_rep_device(driver)
        if DEFAULT_ADAPTER_NAME in self.replication_devices:
            LOG.error('backend_id cannot be `default`')
            raise exception.InvalidConfigurationValue(
                option=('%s.replication_device'
                        % self.default_conf.config_group),
                value=self.default_conf.replication_device)

        # Only support one replication device currently.
        if len(self.replication_devices) > 1:
            LOG.error('At most one replication_device is supported')
            raise exception.InvalidConfigurationValue(
                option=('%s.replication_device'
                        % self.default_conf.config_group),
                value=self.default_conf.replication_device)

        self.is_replication_configured = len(self.replication_devices) >= 1

        self.active_backend_id = driver.active_backend_id
        if self.active_backend_id:
            if self.active_backend_id not in self.replication_devices:
                LOG.error('Service starts under failed-over status, '
                          'active_backend_id: %s is not empty, but not in '
                          'replication_device.', self.active_backend_id)
                raise exception.InvalidConfigurationValue(
                    option=('%s.replication_device'
                            % self.default_conf.config_group),
                    value=self.default_conf.replication_device)
        else:
            self.active_backend_id = DEFAULT_ADAPTER_NAME

        default_device_conf = {
            'backend_id': DEFAULT_ADAPTER_NAME,
            'san_ip': driver.configuration.san_ip
        }
        self.default_device = ReplicationDevice(default_device_conf, driver)
        if not self.is_service_failed_over:
            # If service doesn't fail over, setup the adapter.
            # Otherwise, the primary backend could be down, adapter setup could
            # fail.
            self.default_device.setup_adapter()

        if self.is_replication_configured:
            # If replication_device is configured, consider the replication is
            # enabled and check the same configuration is valid for secondary
            # backend or not.
            self.setup_rep_adapters()

    @property
    def is_service_failed_over(self):
        return (self.active_backend_id is not None
                and self.active_backend_id != DEFAULT_ADAPTER_NAME)

    def setup_rep_adapters(self):
        for backend_id, rep_device in self.replication_devices.items():
            rep_device.setup_adapter()

    @property
    def active_adapter(self):
        if self.is_service_failed_over:
            return self.replication_devices[self.active_backend_id].adapter
        else:
            self.active_backend_id = DEFAULT_ADAPTER_NAME
            return self.default_device.adapter

    @staticmethod
    def parse_rep_device(driver):
        driver_conf = driver.configuration
        rep_devices = {}
        if not driver_conf.replication_device:
            return rep_devices

        for device_conf in driver_conf.replication_device:
            rep_device = ReplicationDevice(device_conf, driver)
            rep_devices[rep_device.backend_id] = rep_device
        return rep_devices

    def failover_service(self, backend_id):
        self.active_backend_id = backend_id
