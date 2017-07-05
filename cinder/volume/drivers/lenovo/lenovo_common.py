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
from cinder.volume.drivers.dothill import dothill_common
from cinder.volume.drivers.lenovo import lenovo_client

common_opts = [
    cfg.StrOpt('lenovo_backend_name',
               default='A',
               help="Pool or Vdisk name to use for volume creation."),
    cfg.StrOpt('lenovo_backend_type',
               choices=['linear', 'virtual'],
               default='virtual',
               help="linear (for VDisk) or virtual (for Pool)."),
    cfg.StrOpt('lenovo_api_protocol',
               choices=['http', 'https'],
               default='https',
               help="Lenovo api interface protocol."),
    cfg.BoolOpt('lenovo_verify_certificate',
                default=False,
                help="Whether to verify Lenovo array SSL certificate."),
    cfg.StrOpt('lenovo_verify_certificate_path',
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


class LenovoCommon(dothill_common.DotHillCommon):
    VERSION = "1.6"

    def __init__(self, config):
        self.config = config
        self.vendor_name = "Lenovo"
        self.backend_name = self.config.lenovo_backend_name
        self.backend_type = self.config.lenovo_backend_type
        self.api_protocol = self.config.lenovo_api_protocol
        ssl_verify = False
        if (self.api_protocol == 'https' and
           self.config.lenovo_verify_certificate):
            ssl_verify = self.config.lenovo_verify_certificate_path or True
        self.client = lenovo_client.LenovoClient(self.config.san_ip,
                                                 self.config.san_login,
                                                 self.config.san_password,
                                                 self.api_protocol,
                                                 ssl_verify)
