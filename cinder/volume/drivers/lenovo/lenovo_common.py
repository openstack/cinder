#    Copyright 2014 Objectif Libre
#    Copyright 2015 DotHill Systems
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
import cinder.volume.drivers.lenovo.lenovo_client as lenovo_client
import cinder.volume.drivers.stx.common as common

common_opts = [
    cfg.StrOpt('lenovo_pool_name',
               deprecated_name='lenovo_backend_name',
               default='A',
               help="Pool or Vdisk name to use for volume creation."),
    cfg.StrOpt('lenovo_pool_type',
               deprecated_name='lenovo_backend_type',
               choices=['linear', 'virtual'],
               default='virtual',
               help="linear (for VDisk) or virtual (for Pool)."),
    cfg.StrOpt('lenovo_api_protocol',
               deprecated_for_removal=True,
               deprecated_reason='driver_use_ssl should be used instead.',
               choices=['http', 'https'],
               default='https',
               help="Lenovo api interface protocol."),
    cfg.BoolOpt('lenovo_verify_certificate',
                deprecated_for_removal=True,
                deprecated_reason='Use driver_ssl_cert_verify instead.',
                default=False,
                help="Whether to verify Lenovo array SSL certificate."),
    cfg.StrOpt('lenovo_verify_certificate_path',
               deprecated_for_removal=True,
               deprecated_reason='Use driver_ssl_cert_path instead.',
               help="Lenovo array SSL certificate path.")
]

iscsi_opts = [
    cfg.ListOpt('lenovo_iscsi_ips',
                default=[],
                help="List of comma-separated target iSCSI IP addresses."),
]

CONF = cfg.CONF
CONF.register_opts(common_opts, group=configuration.SHARED_CONF_GROUP)
CONF.register_opts(iscsi_opts, group=configuration.SHARED_CONF_GROUP)


class LenovoCommon(common.STXCommon):
    VERSION = "2.0"

    def __init__(self, config):
        self.config = config
        self.vendor_name = "Lenovo"
        self.backend_name = self.config.lenovo_pool_name
        self.backend_type = self.config.lenovo_pool_type
        self.api_protocol = self.config.lenovo_api_protocol
        ssl_verify = False
        # check for deprecated options...
        if (self.api_protocol == 'https' and
           self.config.lenovo_verify_certificate):
            ssl_verify = self.config.lenovo_verify_certificate_path or True
        # ...then check common options
        if self.config.driver_use_ssl:
            self.api_protocol = 'https'
        if self.config.driver_ssl_cert_verify:
            ssl_verify = self.config.driver_ssl_cert_path or True

        self.client = lenovo_client.LenovoClient(self.config.san_ip,
                                                 self.config.san_login,
                                                 self.config.san_password,
                                                 self.api_protocol,
                                                 ssl_verify)
