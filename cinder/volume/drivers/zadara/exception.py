# Copyright (c) 2020 Zadara Storage, Inc.
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

"""
Zadara Cinder driver exception handling.
"""

from cinder import exception
from cinder.i18n import _


class ZadaraSessionRequestException(exception.VolumeDriverException):
    message = _("%(msg)s")


class ZadaraCinderInvalidAccessKey(exception.VolumeDriverException):
    message = "Invalid VPSA access key"


class ZadaraVPSANoActiveController(exception.VolumeDriverException):
    message = _("Unable to find any active VPSA controller")


class ZadaraVolumeNotFound(exception.VolumeDriverException):
    message = "%(reason)s"


class ZadaraServerCreateFailure(exception.VolumeDriverException):
    message = _("Unable to create server object for initiator %(name)s")


class ZadaraAttachmentsNotFound(exception.VolumeDriverException):
    message = _("Failed to retrieve attachments for volume %(name)s")


class ZadaraInvalidAttachmentInfo(exception.VolumeDriverException):
    message = _("Invalid attachment info for volume %(name)s: %(reason)s")


class ZadaraServerNotFound(exception.VolumeDriverException):
    message = _("Unable to find server object for initiator %(name)s")
