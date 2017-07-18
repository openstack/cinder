# Copyright (c) 2016 EMC Corporation.
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

from cinder.tests.unit.volume.drivers.dell_emc.vnx import fake_enum


class VNXSystem(object):
    pass


class VNXEnum(fake_enum.Enum):
    pass


class VNXSPEnum(VNXEnum):
    SP_A = 'SP A'
    SP_B = 'SP B'
    CONTROL_STATION = 'Celerra'


class VNXProvisionEnum(VNXEnum):
    # value of spec "provisioning:type"
    THIN = 'thin'
    THICK = 'thick'
    COMPRESSED = 'compressed'
    DEDUPED = 'deduplicated'


class VNXMigrationRate(VNXEnum):
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    ASAP = 'asap'


class VNXTieringEnum(VNXEnum):
    NONE = 'none'
    HIGH_AUTO = 'starthighthenauto'
    AUTO = 'auto'
    HIGH = 'highestavailable'
    LOW = 'lowestavailable'
    NO_MOVE = 'nomovement'


class VNXMirrorViewRecoveryPolicy(VNXEnum):
    MANUAL = 'manual'
    AUTO = 'automatic'


class VNXMirrorViewSyncRate(VNXEnum):
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'


class VNXMirrorImageState(VNXEnum):
    SYNCHRONIZED = 'Synchronized'
    OUT_OF_SYNC = 'Out-of-Sync'
    SYNCHRONIZING = 'Synchronizing'
    CONSISTENT = 'Consistent'
    SCRAMBLED = 'Scrambled'
    INCOMPLETE = 'Incomplete'
    LOCAL_ONLY = 'Local Only'
    EMPTY = 'Empty'


VNXCtrlMethod = fake_enum.VNXCtrlMethod
