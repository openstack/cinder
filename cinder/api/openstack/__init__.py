# Copyright (c) 2013 OpenStack Foundation
#
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
WSGI middleware for OpenStack API controllers.
"""

from oslo_config import cfg


openstack_api_opts = [
    cfg.StrOpt('project_id_regex',
               default=r"[0-9a-f\-]+",
               help=r'The validation regex for project_ids used in urls. '
                    r'This defaults to [0-9a-f\\-]+ if not set, '
                    r'which matches normal uuids created by keystone.'),
]

CONF = cfg.CONF
CONF.register_opts(openstack_api_opts)
