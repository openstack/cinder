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


class StoropsException(Exception):
    message = 'Storops Error.'


class VNXException(StoropsException):
    message = "VNX Error."


class VNXStorageGroupError(VNXException):
    pass


class VNXAttachAluError(VNXException):
    pass


class VNXAluAlreadyAttachedError(VNXAttachAluError):
    message = (
        'LUN already exists in the specified storage group',
        'Requested LUN has already been added to this Storage Group')


class VNXDetachAluError(VNXStorageGroupError):
    pass


class VNXDetachAluNotFoundError(VNXDetachAluError):
    message = 'No such Host LUN in this Storage Group'


class VNXCreateStorageGroupError(VNXStorageGroupError):
    pass


class VNXStorageGroupNameInUseError(VNXCreateStorageGroupError):
    message = 'Storage Group name already in use'


class VNXNoHluAvailableError(VNXStorageGroupError):
    pass


class VNXMigrationError(VNXException):
    pass


class VNXLunNotMigratingError(VNXException):
    pass


class VNXLunSyncCompletedError(VNXMigrationError):
    error_code = 0x714a8021


class VNXTargetNotReadyError(VNXMigrationError):
    message = 'The destination LUN is not available for migration'


class VNXSnapError(VNXException):
    pass


class VNXDeleteAttachedSnapError(VNXSnapError):
    error_code = 0x716d8003


class VNXCreateSnapError(VNXException):
    message = 'Cannot create the snapshot.'


class VNXAttachSnapError(VNXSnapError):
    message = 'Cannot attach the snapshot.'


class VNXDetachSnapError(VNXSnapError):
    message = 'Cannot detach the snapshot.'


class VNXSnapAlreadyMountedError(VNXSnapError):
    error_code = 0x716d8055


class VNXSnapNameInUseError(VNXSnapError):
    error_code = 0x716d8005


class VNXSnapNotExistsError(VNXSnapError):
    message = 'The specified snapshot does not exist.'


class VNXLunError(VNXException):
    pass


class VNXCreateLunError(VNXLunError):
    pass


class VNXLunNameInUseError(VNXCreateLunError):
    error_code = 0x712d8d04


class VNXLunExtendError(VNXLunError):
    pass


class VNXLunExpandSizeError(VNXLunExtendError):
    error_code = 0x712d8e04


class VNXLunPreparingError(VNXLunError):
    error_code = 0x712d8e0e


class VNXLunNotFoundError(VNXLunError):
    message = 'Could not retrieve the specified (pool lun).'


class VNXDeleteLunError(VNXLunError):
    pass


class VNXLunUsedByFeatureError(VNXLunError):
    pass


class VNXCompressionError(VNXLunError):
    pass


class VNXCompressionAlreadyEnabledError(VNXCompressionError):
    message = 'Compression on the specified LUN is already turned on.'


class VNXConsistencyGroupError(VNXException):
    pass


class VNXCreateConsistencyGroupError(VNXConsistencyGroupError):
    pass


class VNXConsistencyGroupNameInUseError(VNXCreateConsistencyGroupError):
    error_code = 0x716d8021


class VNXConsistencyGroupNotFoundError(VNXConsistencyGroupError):
    message = 'Cannot find the consistency group'


class VNXPingNodeError(VNXException):
    pass


class VNXMirrorException(VNXException):
    pass


class VNXMirrorNameInUseError(VNXMirrorException):
    message = 'Mirror name already in use'


class VNXMirrorPromotePrimaryError(VNXMirrorException):
    message = 'Cannot remove or promote a primary image.'


class VNXMirrorNotFoundError(VNXMirrorException):
    message = 'Mirror not found'


class VNXMirrorGroupNameInUseError(VNXMirrorException):
    message = 'Mirror Group name already in use'


class VNXMirrorGroupNotFoundError(VNXMirrorException):
    message = 'Unable to locate the specified group'


class VNXMirrorGroupAlreadyMemberError(VNXMirrorException):
    message = 'The mirror is already a member of a group'


class VNXMirrorGroupMirrorNotMemberError(VNXMirrorException):
    message = 'The specified mirror is not a member of the group'


class VNXMirrorGroupAlreadyPromotedError(VNXMirrorException):
    message = 'The Consistency Group has no secondary images to promote'
