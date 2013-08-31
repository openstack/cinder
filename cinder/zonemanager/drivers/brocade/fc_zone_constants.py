#    (c) Copyright 2014 Brocade Communications Systems Inc.
#    All Rights Reserved.
#
#    Copyright 2014 OpenStack Foundation
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
CFG_SHOW_TRANS = 'cfgtransshow'
CFG_ZONE_TRANS_ABORT = 'cfgtransabort'
NS_SHOW = 'nsshow'
NS_CAM_SHOW = 'nscamshow'
