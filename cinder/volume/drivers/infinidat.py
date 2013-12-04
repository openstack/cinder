# Copyright 2013 Infinidat Ltd.
# Copyright (c) 2013 OpenStack Foundation
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
Infinidat volume driver for Infinibox.
"""
from cinder.openstack.common import log as logging
from cinder.volume.drivers.san import san
from cinder import exception

LOG = logging.getLogger(__name__)

try:
    from infinidat_openstack.cinder import InfiniboxVolumeDriver
except ImportError:
    LOG.info(_('infi.openstack package not installed.  '
               'Install infinidat_openstack by using pip or easy_install.'))
    class InfiniboxVolumeDriver(san.SanDriver):
        def __init__(self, *args, **kwargs):
            raise exception.CinderException("infinidat_openstack not installed, cannot use Infinibox driver")
