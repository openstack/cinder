#    (c) Copyright 2014 Brocade Communications Systems Inc.
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
from oslo_log import log as logging

from cinder.volume import configuration

brcd_zone_opts = [
    cfg.StrOpt('fc_southbound_protocol',
               default='HTTP',
               choices=('SSH', 'HTTP', 'HTTPS'),
               help='South bound connector for the fabric.'),
    cfg.StrOpt('fc_fabric_address',
               default='',
               help='Management IP of fabric.'),
    cfg.StrOpt('fc_fabric_user',
               default='',
               help='Fabric user ID.'),
    cfg.StrOpt('fc_fabric_password',
               default='',
               help='Password for user.',
               secret=True),
    cfg.PortOpt('fc_fabric_port',
                default=22,
                help='Connecting port'),
    cfg.StrOpt('fc_fabric_ssh_cert_path',
               default='',
               help='Local SSH certificate Path.'),
    cfg.StrOpt('zoning_policy',
               default='initiator-target',
               help='Overridden zoning policy.'),
    cfg.BoolOpt('zone_activate',
                default=True,
                help='Overridden zoning activation state.'),
    cfg.StrOpt('zone_name_prefix',
               default='openstack',
               help='Overridden zone name prefix.'),
    cfg.StrOpt('fc_virtual_fabric_id',
               default=None,
               help='Virtual Fabric ID.')
]

CONF = cfg.CONF
CONF.register_opts(brcd_zone_opts, group='BRCD_FABRIC_EXAMPLE')
LOG = logging.getLogger(__name__)


def load_fabric_configurations(fabric_names):
    fabric_configs = {}
    for fabric_name in fabric_names:
        config = configuration.Configuration(brcd_zone_opts, fabric_name)
        LOG.debug("Loaded FC fabric config %(fabricname)s",
                  {'fabricname': fabric_name})
        fabric_configs[fabric_name] = config
    return fabric_configs
