# Copyright 2013 OpenStack Foundation.
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

import oslo.config.cfg

import cinder.openstack.common.importutils

_compute_opts = [
    oslo.config.cfg.StrOpt('compute_api_class',
                           default='cinder.compute.nova.API',
                           help='The full class name of the '
                                'compute API class to use'),
]

oslo.config.cfg.CONF.register_opts(_compute_opts)


def API():
    importutils = cinder.openstack.common.importutils
    compute_api_class = oslo.config.cfg.CONF.compute_api_class
    cls = importutils.import_class(compute_api_class)
    return cls()
