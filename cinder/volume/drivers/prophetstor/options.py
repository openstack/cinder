# Copyright (c) 2014 ProphetStor, Inc.
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


from oslo_config import cfg


DPL_OPTS = [
    cfg.StrOpt('dpl_pool',
               default='',
               help='DPL pool uuid in which DPL volumes are stored.'),
    cfg.IntOpt('dpl_port',
               default=8357,
               help='DPL port number.'),
]

CONF = cfg.CONF
CONF.register_opts(DPL_OPTS)
