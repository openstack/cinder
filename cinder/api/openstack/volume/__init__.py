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

from cinder.api.v1.router import APIRouter as v1_router
from cinder.i18n import _
from cinder.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class APIRouter(v1_router):
    def __init__(self, ext_mgr=None):
        LOG.warn(_('cinder.api.openstack.volume:APIRouter is deprecated. '
                 'Please use cinder.api.v1.router:APIRouter instead.'))
        super(APIRouter, self).__init__(ext_mgr)
