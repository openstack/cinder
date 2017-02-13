# Copyright (c) 2018 Hedvig, Inc.
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


class Config(object):
    ReplicationPolicy = {
        0: "Agnostic",
        1: "RackAware",
        2: "DataCenterAware",
    }

    DiskResidence = {
        0: "Flash",
        1: "HDD",
    }

    # Default Port Configuration
    defaultHControllerPort_ = 50000

    # Default Cinder Configuration
    defaultCinderReplicationFactor = 3
    defaultCinderDedupEnable = False
    defaultCinderCompressEnable = False
    defaultCinderCacheEnable = False
    defaultCinderDiskResidence = DiskResidence[1]
    defaultCinderReplicationPolicy = ReplicationPolicy[0]
    retryCount = 5
