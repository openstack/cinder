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

from cinder import exception
from cinder.i18n import _


class InvalidBackend(exception.VolumeDriverException):
    message = _("Backend doesn't exist (%(backend)s)")


class ConnectionError(exception.VolumeDriverException):
    message = "%(message)s"


class AuthenticationError(exception.VolumeDriverException):
    message = "%(message)s"


class NotEnoughSpace(exception.VolumeDriverException):
    message = _("Not enough space on backend (%(backend)s)")


class RequestError(exception.VolumeDriverException):
    message = "%(message)s"


class NotTargetPortal(exception.VolumeDriverException):
    message = _("No active iSCSI portals with supplied iSCSI IPs")
