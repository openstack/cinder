# Copyright (c) 2016 Pure Storage, Inc.
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

from tempest import config

from cinder.tests.tempest.services import consistencygroups_client
from cinder.tests.tempest.services import volume_revert_client

CONF = config.CONF


class Manager(object):
    def __init__(self, base_manager):
        params = {
            'service': CONF.volume.catalog_type,
            'region': CONF.volume.region or CONF.identity.region,
            'endpoint_type': CONF.volume.endpoint_type,
            'build_interval': CONF.volume.build_interval,
            'build_timeout': CONF.volume.build_timeout
        }
        params.update(base_manager.default_params)
        auth_provider = base_manager.auth_provider

        self.consistencygroups_adm_client = (
            consistencygroups_client.ConsistencyGroupsClient(auth_provider,
                                                             **params))
        self.volume_revet_client = (
            volume_revert_client.VolumeRevertClient(auth_provider, **params))
