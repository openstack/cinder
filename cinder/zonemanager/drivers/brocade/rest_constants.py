#    (c) Copyright 2019 Brocade, a Broadcom Company
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

YANG = "application/yang-data+json"
ACCEPT = "Accept"
CONTENT_TYPE = "Content-Type"
AUTHORIZATION = "Authorization"
USER_AGENT = "User-Agent"
ZONE_DRIVER = "OpenStack Zone Driver"
LOGIN = "/rest/login"
LOGOUT = "/rest/logout"
NAME_SERVER = "/rest/running/brocade-name-server"
ZONING = "/rest/running/zoning"
DEFINED_CFG = "/defined-configuration"
EFFECTIVE_CFG = "/effective-configuration"
GET_SWITCH = "/rest/running/switch/fibrechannel-switch"
GET_NAMESERVER = NAME_SERVER + "/fibrechannel-name-server"
GET_DEFINED_ZONE_CFG = ZONING + DEFINED_CFG
GET_ACTIVE_ZONE_CFG = ZONING + EFFECTIVE_CFG
GET_CHECKSUM = ZONING + EFFECTIVE_CFG + "/checksum"
POST_ZONE = ZONING + DEFINED_CFG + "/zone/zone-name/"
POST_CFG = ZONING + DEFINED_CFG + "/cfg/cfg-name/"
PATCH_CFG = ZONING + DEFINED_CFG + "/cfg/cfg-name/"
PATCH_CFG_SAVE = ZONING + EFFECTIVE_CFG + "/cfg-action/1"
PATCH_CFG_DISABLE = ZONING + EFFECTIVE_CFG + "/cfg-action/2"
PATCH_CFG_ENABLE = ZONING + EFFECTIVE_CFG + "/cfg-name/"
DELETE_ZONE = POST_ZONE
DELETE_CFG = POST_CFG
RESPONSE = "Response"
SWITCH = "fibrechannel-switch"
FIRMWARE_VERSION = "firmware-version"
FC_NAME_SERVER = "fibrechannel-name-server"
PORT_NAME = "port-name"
DEFINED_CFG = "defined-configuration"
CFG = "cfg"
CFG_NAME = "cfg-name"
MEMBER_ZONE = "member-zone"
ZONE_NAME = "zone-name"
ZONE = "zone"
MEMBER_ENTRY = "member-entry"
ENTRY_NAME = "entry-name"
ALIAS = "alias"
ALIAS_ENTRY_NAME = "alias-entry-name"
EFFECTIVE_CFG = "effective-configuration"
CHECKSUM = "checksum"
ENABLED_ZONE = "enabled-zone"
