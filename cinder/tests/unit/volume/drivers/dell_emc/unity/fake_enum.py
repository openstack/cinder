# Copyright (c) 2017-2019 Dell Inc. or its subsidiaries.
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
import enum


class TieringPolicyEnum(enum.Enum):
    AUTOTIER_HIGH = (0, 'Start Highest and Auto-tier')
    AUTOTIER = (1, 'Auto-tier')
    HIGHEST = (2, 'Highest')
    LOWEST = (3, 'Lowest')
    NO_DATA_MOVEMENT = (4, 'No Data Movement')
    MIXED = (0xffff, 'Different Tier Policies')
