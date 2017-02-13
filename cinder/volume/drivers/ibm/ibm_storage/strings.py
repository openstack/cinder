#  Copyright (c) 2016 IBM Corporation
#  All Rights Reserved.
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

# General
TITLE = "IBM Storage"
DEFAULT = "Default"

# PROMPTS
CERTIFICATES_PATH = "/opt/ibm/ds8k_certs/"

# DEFAULT INSTALLED VALUES
XIV_BACKEND_PREFIX = "IBM-XIV"
DS8K_BACKEND_PREFIX = "IBM-DS8K"

# Replication Status Strings
REPLICATION_STATUS_DISABLED = 'disabled'  # no replication
REPLICATION_STATUS_ERROR = 'error'  # replication in error state
# replication copying data to secondary (inconsistent)
REPLICATION_STATUS_COPYING = 'copying'
# replication copying data to secondary (consistent)
REPLICATION_STATUS_ACTIVE = 'active'
# replication copying data to secondary (consistent)
REPLICATION_STATUS_ACTIVE_STOPPED = 'active-stopped'
# replication copying data to secondary (consistent)
REPLICATION_STATUS_INACTIVE = 'inactive'

# Replication Failback String
PRIMARY_BACKEND_ID = 'default'

# Volume Extra Metadata Default Value
METADATA_IS_TRUE = '<IS> TRUE'
