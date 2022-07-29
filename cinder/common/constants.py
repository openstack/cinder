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

# The encryption key ID used by the legacy fixed-key ConfKeyMgr
FIXED_KEY_ID = '00000000-0000-0000-0000-000000000000'

# Storage protocol constants
CEPH = 'ceph'
DRBD = 'DRBD'
FC = 'FC'
FC_VARIANT_1 = 'fibre_channel'
FC_VARIANT_2 = 'fc'
FILE = 'file'
ISCSI = 'iSCSI'
ISCSI_VARIANT = 'iscsi'
ISER = 'iSER'
LIGHTOS = 'lightos'
NFS = 'NFS'
NFS_VARIANT = 'nfs'
NVMEOF = 'NVMe-oF'
NVMEOF_VARIANT_1 = 'NVMeOF'
NVMEOF_VARIANT_2 = 'nvmeof'
NVMEOF_ROCE = 'NVMe-RoCE'
NVMEOF_FC = 'NVMe-FC'
NVMEOF_TCP = 'NVMe-TCP'
SCALEIO = 'scaleio'
SCSI = 'SCSI'
STORPOOL = 'storpool'
VMDK = 'vmdk'
VSTORAGE = 'vstorageobject'

# These must be strings, because there are places that check specific type
ISCSI_VARIANTS = [ISCSI, ISCSI_VARIANT]
FC_VARIANTS = [FC, FC_VARIANT_1, FC_VARIANT_2]
NFS_VARIANTS = [NFS, NFS_VARIANT]
NVMEOF_VARIANTS = [NVMEOF, NVMEOF_VARIANT_1, NVMEOF_VARIANT_2]

CACHEABLE_PROTOCOLS = FC_VARIANTS + ISCSI_VARIANTS + NVMEOF_VARIANTS
