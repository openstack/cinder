# Copyright (c) 2012 OpenStack Foundation
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
Request Body limiting middleware.
Compatibility shim for Kilo, while operators migrate to oslo.middleware.
"""


from oslo_config import cfg
from oslo_middleware import sizelimit

from cinder.openstack.common import versionutils


# Default request size is 112k
max_request_body_size_opt = cfg.IntOpt('osapi_max_request_body_size',
                                       default=114688,
                                       help='Max size for body of a request')

CONF = cfg.CONF
CONF.register_opt(max_request_body_size_opt)


@versionutils.deprecated(as_of=versionutils.deprecated.KILO,
                         in_favor_of='oslo_middleware.RequestBodySizeLimiter')
class RequestBodySizeLimiter(sizelimit.RequestBodySizeLimiter):
    """Add a 'cinder.context' to WSGI environ."""
    pass
