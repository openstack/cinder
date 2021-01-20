#    Copyright 2014 Objectif Libre
#    Copyright 2015 DotHill Systems
#    Copyright 2016-2020 Seagate Technology or one of its affiliates
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
#

from oslo_config import cfg

from cinder.volume import configuration
from cinder.volume import driver
import cinder.volume.drivers.dell_emc.powervault.client as pvme_client
import cinder.volume.drivers.stx.common as common

common_opts = [
    cfg.StrOpt('pvme_pool_name',
               default='A',
               help="Pool or Vdisk name to use for volume creation."),
]

iscsi_opts = [
    cfg.ListOpt('pvme_iscsi_ips',
                default=[],
                help="List of comma-separated target iSCSI IP addresses."),
]

CONF = cfg.CONF
CONF.register_opts(common_opts, group=configuration.SHARED_CONF_GROUP)
CONF.register_opts(iscsi_opts, group=configuration.SHARED_CONF_GROUP)


class PVMECommon(common.STXCommon):
    VERSION = "2.0"

    def __init__(self, config):
        self.config = config
        self.vendor_name = "PVME"
        self.backend_name = self.config.pvme_pool_name
        self.backend_type = 'virtual'
        self.api_protocol = 'http'
        if self.config.driver_use_ssl:
            self.api_protocol = 'https'
        ssl_verify = self.config.driver_ssl_cert_verify
        if ssl_verify and self.config.driver_ssl_cert_path:
            ssl_verify = self.config.driver_ssl_cert_path

        self.client = pvme_client.PVMEClient(self.config.san_ip,
                                             self.config.san_login,
                                             self.config.san_password,
                                             self.api_protocol,
                                             ssl_verify)

    @staticmethod
    def get_driver_options():
        additional_opts = driver.BaseVD._get_oslo_driver_opts(
            'san_ip', 'san_login', 'san_password', 'driver_use_ssl',
            'driver_ssl_cert_verify', 'driver_ssl_cert_path')
        return common_opts + additional_opts
