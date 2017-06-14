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
""" Fake pyxcli exceptions for testing the driver without installing pyxcli"""


class XCLIError(Exception):
    pass


class VolumeBadNameError(XCLIError):
    pass


class CredentialsError(XCLIError):
    pass


class ConnectionError(XCLIError):
    pass


class CgHasMirrorError(XCLIError):
    pass


class CgDoesNotExistError(XCLIError):
    pass


class CgEmptyError(XCLIError):
    pass


class PoolSnapshotLimitReachedError(XCLIError):
    pass


class CommandFailedRuntimeError(XCLIError):
    pass


class PoolOutOfSpaceError(XCLIError):
    pass


class CgLimitReachedError(XCLIError):
    pass


class HostBadNameError(XCLIError):
    pass


class CgNotEmptyError(XCLIError):
    pass


class SystemOutOfSpaceError(XCLIError):
    pass


class CgNameExistsError(XCLIError):
    pass


class CgBadNameError(XCLIError):
    pass


class SnapshotGroupDoesNotExistError(XCLIError):
    pass


class ClosedTransportError(XCLIError):
    pass


class VolumeNotInConsGroup(XCLIError):
    pass
