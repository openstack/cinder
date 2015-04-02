# (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Exceptions for the Brick library."""

from oslo_log import log as logging
import six

from cinder.i18n import _


LOG = logging.getLogger(__name__)


class BrickException(Exception):
    """Base Brick Exception

    To correctly use this class, inherit from it and define
    a 'msg_fmt' property. That msg_fmt will get printf'd
    with the keyword arguments provided to the constructor.
    """
    message = _("An unknown exception occurred.")
    code = 500
    headers = {}
    safe = False

    def __init__(self, message=None, **kwargs):
        self.kwargs = kwargs

        if 'code' not in self.kwargs:
            try:
                self.kwargs['code'] = self.code
            except AttributeError:
                pass

        if not message:
            try:
                message = self.message % kwargs

            except Exception:
                # kwargs doesn't match a variable in the message
                # log the issue and the kwargs
                msg = (_("Exception in string format operation.  msg='%s'")
                       % self.message)
                LOG.exception(msg)
                for name, value in kwargs.iteritems():
                    LOG.error("%s: %s" % (name, value))

                # at least get the core message out if something happened
                message = self.message

        # Put the message in 'msg' so that we can access it.  If we have it in
        # message it will be overshadowed by the class' message attribute
        self.msg = message
        super(BrickException, self).__init__(message)

    def __unicode__(self):
        return six.text_type(self.msg)


class NotFound(BrickException):
    message = _("Resource could not be found.")
    code = 404
    safe = True


class Invalid(BrickException):
    message = _("Unacceptable parameters.")
    code = 400


# Cannot be templated as the error syntax varies.
# msg needs to be constructed when raised.
class InvalidParameterValue(Invalid):
    message = _("%(err)s")


class NoFibreChannelHostsFound(BrickException):
    message = _("We are unable to locate any Fibre Channel devices.")


class NoFibreChannelVolumeDeviceFound(BrickException):
    message = _("Unable to find a Fibre Channel volume device.")


class VolumeDeviceNotFound(BrickException):
    message = _("Volume device not found at %(device)s.")


class VolumePathNotRemoved(BrickException):
    message = _("Volume path %(volume_path)s was not removed in time.")


class VolumeGroupNotFound(BrickException):
    message = _('Unable to find Volume Group: %(vg_name)s')


class VolumeGroupCreationFailed(BrickException):
    message = _('Failed to create Volume Group: %(vg_name)s')


class ISCSITargetCreateFailed(BrickException):
    message = _("Failed to create iscsi target for volume %(volume_id)s.")


class ISCSITargetRemoveFailed(BrickException):
    message = _("Failed to remove iscsi target for volume %(volume_id)s.")


class ISCSITargetAttachFailed(BrickException):
    message = _("Failed to attach iSCSI target for volume %(volume_id)s.")


class ProtocolNotSupported(BrickException):
    message = _("Connect to volume via protocol %(protocol)s not supported.")
