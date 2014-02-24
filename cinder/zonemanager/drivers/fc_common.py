#    (c) Copyright 2014 Brocade Communications Systems Inc.
#    All Rights Reserved.
#
#    Copyright 2014 OpenStack Foundation
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


from oslo.config import cfg

san_context_opts = [
    cfg.StrOpt('fc_fabric_names',
               default=None,
               help='Comma separated list of fibre channel fabric names.'
               ' This list of names is used to retrieve other SAN credentials'
               ' for connecting to each SAN fabric'),
]

CONF = cfg.CONF
CONF.register_opts(san_context_opts)


class FCCommon(object):
    """Common interface for FC operations."""

    def __init__(self, **kwargs):
        pass
