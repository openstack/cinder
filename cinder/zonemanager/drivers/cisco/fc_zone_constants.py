#    (c) Copyright 2014 Cisco Systems Inc.
#    All Rights Reserved.
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


"""
Common constants used by Cisco FC Zone Driver.
"""
ACTIVE_ZONE_CONFIG = 'active_zone_config'
CFG_ZONESET = 'zoneset'
CFG_ZONE = 'zone'
CFG_ZONE_MEMBER = 'pwwn'
CFG_ZONES = 'zones'

"""
CLI Commands for FC zoning operations.
"""
GET_ACTIVE_ZONE_CFG = 'show zoneset active vsan '
FCNS_SHOW = 'show fcns database vsan '
GET_ZONE_STATUS = 'show zone status vsan '
