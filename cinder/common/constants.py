# Copyright 2016 Red Hat, Inc.
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


# The maximum value a signed INT type may have
DB_MAX_INT = 0x7FFFFFFF

# The cinder services binaries and topics' names
API_BINARY = "cinder-api"
SCHEDULER_BINARY = "cinder-scheduler"
VOLUME_BINARY = "cinder-volume"
BACKUP_BINARY = "cinder-backup"
SCHEDULER_TOPIC = SCHEDULER_BINARY
VOLUME_TOPIC = VOLUME_BINARY
BACKUP_TOPIC = BACKUP_BINARY
LOG_BINARIES = (SCHEDULER_BINARY, VOLUME_BINARY, BACKUP_BINARY, API_BINARY)
