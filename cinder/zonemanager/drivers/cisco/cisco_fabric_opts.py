#    (c) Copyright 2014 Cisco Systems Inc.
#    All Rights Reserved.
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

cisco_zone_opts = [
    cfg.StrOpt('cisco_fc_fabric_address',
               default='',
               help='Management IP of fabric'),
    cfg.StrOpt('cisco_fc_fabric_user',
               default='',
               help='Fabric user ID'),
    cfg.StrOpt('cisco_fc_fabric_password',
               default='',
               help='Password for user',
               secret=True),
    cfg.IntOpt('cisco_fc_fabric_port',
               default=22,
               help='Connecting port'),
    cfg.StrOpt('cisco_zoning_policy',
               default='initiator-target',
               help='overridden zoning policy'),
    cfg.BoolOpt('cisco_zone_activate',
                default=True,
                help='overridden zoning activation state'),
    cfg.StrOpt('cisco_zone_name_prefix',
               default=None,
               help='overridden zone name prefix'),
    cfg.StrOpt('cisco_zoning_vsan',
               default=None,
               help='VSAN of the Fabric'),
]

CONF = cfg.CONF
CONF.register_opts(cisco_zone_opts, 'CISCO_FABRIC_EXAMPLE')


def load_fabric_configurations(fabric_names):
    fabric_configs = {}
    for fabric_name in fabric_names:
        config = configuration.Configuration(cisco_zone_opts, fabric_name)
        fabric_configs[fabric_name] = config

    return fabric_configs
