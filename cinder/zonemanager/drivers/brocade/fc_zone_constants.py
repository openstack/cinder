#    (c) Copyright 2016 Brocade Communications Systems Inc.
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
Common constants used by Brocade FC Zone Driver.
"""
YES = 'y'
ACTIVE_ZONE_CONFIG = 'active_zone_config'
CFG_ZONESET = 'cfg:'
CFG_ZONES = 'zones'
OPENSTACK_CFG_NAME = 'OpenStack_Cfg'
SUCCESS = 'Success'
TRANS_ABORTABLE = 'It is abortable'

"""
CLI Commands for FC zoning operations.
"""
GET_ACTIVE_ZONE_CFG = 'cfgactvshow'
ZONE_CREATE = 'zonecreate '
ZONESET_CREATE = 'cfgcreate '
CFG_SAVE = 'cfgsave'
CFG_ADD = 'cfgadd '
ACTIVATE_ZONESET = 'cfgenable '
DEACTIVATE_ZONESET = 'cfgdisable'
CFG_DELETE = 'cfgdelete '
CFG_REMOVE = 'cfgremove '
ZONE_DELETE = 'zonedelete '
ZONE_ADD = 'zoneadd '
ZONE_REMOVE = 'zoneremove '
CFG_SHOW_TRANS = 'cfgtransshow'
CFG_ZONE_TRANS_ABORT = 'cfgtransabort'
NS_SHOW = 'nsshow'
NS_CAM_SHOW = 'nscamshow'

"""
HTTPS connector constants
"""
AUTH_HEADER = "Authorization"
PROTOCOL_HTTPS = "HTTPS"
STATUS_OK = 200
SECINFO_PAGE = "/secinfo.html"
AUTHEN_PAGE = "/authenticate.html"
GET_METHOD = "GET"
POST_METHOD = "POST"
SECINFO_BEGIN = "--BEGIN SECINFO"
SECINFO_END = "--END SECINFO"
RANDOM = "RANDOM"
AUTH_STRING = "Custom_Basic "  # Trailing space is required, do not remove
AUTHEN_BEGIN = "--BEGIN AUTHENTICATE"
AUTHEN_END = "--END AUTHENTICATE"
AUTHENTICATED = "authenticated"
SESSION_PAGE_ACTION = "/session.html?action=query"
SESSION_BEGIN = "--BEGIN SESSION"
SESSION_END = "--END SESSION"
SESSION_PAGE = "/session.html"
LOGOUT_PAGE = "/logout.html"
ZONEINFO_BEGIN = "--BEGIN ZONE INFO"
ZONEINFO_END = "--END ZONE INFO"
SWITCH_PAGE = "/switch.html"
SWITCHINFO_BEGIN = "--BEGIN SWITCH INFORMATION"
SWITCHINFO_END = "--END SWITCH INFORMATION"
FIRMWARE_VERSION = "swFWVersion"
VF_ENABLED = "vfEnabled"
MANAGEABLE_VF = "manageableLFList"
CHANGE_VF = ("Session=--BEGIN SESSION\n\taction=apply\n\tLFId=  {vfid}  "
             "\b\t--END SESSION")
ZONE_TRAN_STATUS = "/gzoneinfo.htm?txnId={txnId}"
CFG_DELIM = "\x01"
ZONE_DELIM = "\x02"
ALIAS_DELIM = "\x03"
QLP_DELIM = "\x04"
ZONE_END_DELIM = "\x05&saveonly="
IFA_DELIM = "\x06"
ACTIVE_CFG_DELIM = "\x07"
DEFAULT_CFG = "d__efault__Cfg"
NS_PAGE = "/nsinfo.htm"
NSINFO_BEGIN = "--BEGIN NS INFO"
NSINFO_END = "--END NS INFO"
NS_DELIM = ";N    ;"
ZONE_TX_BEGIN = "--BEGIN ZONE_TXN_INFO"
ZONE_TX_END = "--END ZONE_TXN_INFO"
ZONE_ERROR_CODE = "errorCode"
ZONE_PAGE = "/gzoneinfo.htm"
CFG_NAME = "openstack_cfg"
ZONE_STRING_PREFIX = "zonecfginfo="
ZONE_ERROR_MSG = "errorMessage"
ZONE_TX_ID = "txnId"
ZONE_TX_STATUS = "status"
SESSION_LF_ID = "sessionLFId"
HTTP = "http"
HTTPS = "https"
