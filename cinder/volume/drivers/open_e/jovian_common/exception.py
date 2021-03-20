#    Copyright (c) 2020 Open-E, Inc.
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

from cinder import exception
from cinder.i18n import _


class JDSSException(exception.VolumeDriverException):
    """Unknown error"""
    message = _("%(reason)s")


class JDSSRESTException(JDSSException):
    """Unknown communication error"""

    message = _("JDSS REST request %(request)s faild: %(reason)s.")


class JDSSRESTProxyException(JDSSException):
    """Connection with host failed"""

    message = _("JDSS connection with %(host)s failed: %(reason)s.")


class JDSSResourceNotFoundException(JDSSException):
    """Resource does not exist"""

    message = _("JDSS resource %(res)s DNE.")


class JDSSVolumeNotFoundException(JDSSResourceNotFoundException):
    """Volume does not exist"""

    message = _("JDSS volume %(volume)s DNE.")


class JDSSSnapshotNotFoundException(JDSSResourceNotFoundException):
    """Snapshot does not exist"""

    message = _("JDSS snapshot %(snapshot)s DNE.")


class JDSSResourceExistsException(JDSSException):
    """Resource with specified id exists"""

    message = _("JDSS resource with id %(res)s exists.")


class JDSSSnapshotExistsException(JDSSResourceExistsException):
    """Snapshot with the same id exists"""

    message = _("JDSS snapshot %(snapshot)s already exists.")


class JDSSVolumeExistsException(JDSSResourceExistsException):
    """Volume with same id exists"""

    message = _("JDSS volume %(volume)s already exists.")


class JDSSResourceIsBusyException(JDSSException):
    """Resource have dependents"""

    message = _("JDSS resource %(res)s is busy.")


class JDSSSnapshotIsBusyException(JDSSResourceIsBusyException):
    """Snapshot have dependent clones"""

    message = _("JDSS snapshot %(snapshot)s is busy.")


class JDSSOSException(JDSSException):
    """Storage internal system error"""

    message = _("JDSS internal system error %(message)s.")
