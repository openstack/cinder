# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Cinder base exception handling.

Includes decorator for re-raising Cinder-type exceptions.

SHOULD include dedicated exception logging.

"""

import sys

from oslo.config import cfg
import webob.exc

from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import log as logging


LOG = logging.getLogger(__name__)

exc_log_opts = [
    cfg.BoolOpt('fatal_exception_format_errors',
                default=False,
                help='make exception message format errors fatal'),
]

CONF = cfg.CONF
CONF.register_opts(exc_log_opts)


class ConvertedException(webob.exc.WSGIHTTPException):
    def __init__(self, code=0, title="", explanation=""):
        self.code = code
        self.title = title
        self.explanation = explanation
        super(ConvertedException, self).__init__()


class Error(Exception):
    pass


class CinderException(Exception):
    """Base Cinder Exception

    To correctly use this class, inherit from it and define
    a 'message' property. That message will get printf'd
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
                exc_info = sys.exc_info()
                # kwargs doesn't match a variable in the message
                # log the issue and the kwargs
                LOG.exception(_('Exception in string format operation'))
                for name, value in kwargs.iteritems():
                    LOG.error("%s: %s" % (name, value))
                if CONF.fatal_exception_format_errors:
                    raise exc_info[0], exc_info[1], exc_info[2]
                # at least get the core message out if something happened
                message = self.message

        # NOTE(luisg): We put the actual message in 'msg' so that we can access
        # it, because if we try to access the message via 'message' it will be
        # overshadowed by the class' message attribute
        self.msg = message
        super(CinderException, self).__init__(message)

    def __unicode__(self):
        return unicode(self.msg)


class VolumeBackendAPIException(CinderException):
    message = _("Bad or unexpected response from the storage volume "
                "backend API: %(data)s")


class VolumeDriverException(CinderException):
    message = _("Volume driver reported an error: %(message)s")


class BackupDriverException(CinderException):
    message = _("Backup driver reported an error: %(message)s")


class GlanceConnectionFailed(CinderException):
    message = _("Connection to glance failed: %(reason)s")


class NotAuthorized(CinderException):
    message = _("Not authorized.")
    code = 403


class AdminRequired(NotAuthorized):
    message = _("User does not have admin privileges")


class PolicyNotAuthorized(NotAuthorized):
    message = _("Policy doesn't allow %(action)s to be performed.")


class ImageNotAuthorized(CinderException):
    message = _("Not authorized for image %(image_id)s.")


class DriverNotInitialized(CinderException):
    message = _("Volume driver not ready.")


class Invalid(CinderException):
    message = _("Unacceptable parameters.")
    code = 400


class InvalidSnapshot(Invalid):
    message = _("Invalid snapshot: %(reason)s")


class InvalidVolumeAttachMode(Invalid):
    message = _("Invalid attaching mode '%(mode)s' for "
                "volume %(volume_id)s.")


class VolumeAttached(Invalid):
    message = _("Volume %(volume_id)s is still attached, detach volume first.")


class SfJsonEncodeFailure(CinderException):
    message = _("Failed to load data into json format")


class InvalidResults(Invalid):
    message = _("The results are invalid.")


class InvalidInput(Invalid):
    message = _("Invalid input received: %(reason)s")


class InvalidVolumeType(Invalid):
    message = _("Invalid volume type: %(reason)s")


class InvalidVolume(Invalid):
    message = _("Invalid volume: %(reason)s")


class InvalidContentType(Invalid):
    message = _("Invalid content type %(content_type)s.")


class InvalidHost(Invalid):
    message = _("Invalid host: %(reason)s")


# Cannot be templated as the error syntax varies.
# msg needs to be constructed when raised.
class InvalidParameterValue(Invalid):
    message = _("%(err)s")


class InvalidAuthKey(Invalid):
    message = _("Invalid auth key: %(reason)s")


class InvalidConfigurationValue(Invalid):
    message = _('Value "%(value)s" is not valid for '
                'configuration option "%(option)s"')


class ServiceUnavailable(Invalid):
    message = _("Service is unavailable at this time.")


class ImageUnacceptable(Invalid):
    message = _("Image %(image_id)s is unacceptable: %(reason)s")


class DeviceUnavailable(Invalid):
    message = _("The device in the path %(path)s is unavailable: %(reason)s")


class InvalidUUID(Invalid):
    message = _("Expected a uuid but received %(uuid)s.")


class NotFound(CinderException):
    message = _("Resource could not be found.")
    code = 404
    safe = True


class VolumeNotFound(NotFound):
    message = _("Volume %(volume_id)s could not be found.")


class VolumeMetadataNotFound(NotFound):
    message = _("Volume %(volume_id)s has no metadata with "
                "key %(metadata_key)s.")


class VolumeAdminMetadataNotFound(NotFound):
    message = _("Volume %(volume_id)s has no administration metadata with "
                "key %(metadata_key)s.")


class InvalidVolumeMetadata(Invalid):
    message = _("Invalid metadata: %(reason)s")


class InvalidVolumeMetadataSize(Invalid):
    message = _("Invalid metadata size: %(reason)s")


class SnapshotMetadataNotFound(NotFound):
    message = _("Snapshot %(snapshot_id)s has no metadata with "
                "key %(metadata_key)s.")


class VolumeTypeNotFound(NotFound):
    message = _("Volume type %(volume_type_id)s could not be found.")


class VolumeTypeNotFoundByName(VolumeTypeNotFound):
    message = _("Volume type with name %(volume_type_name)s "
                "could not be found.")


class VolumeTypeExtraSpecsNotFound(NotFound):
    message = _("Volume Type %(volume_type_id)s has no extra specs with "
                "key %(extra_specs_key)s.")


class VolumeTypeInUse(CinderException):
    message = _("Volume Type %(volume_type_id)s deletion is not allowed with "
                "volumes present with the type.")


class SnapshotNotFound(NotFound):
    message = _("Snapshot %(snapshot_id)s could not be found.")


class VolumeIsBusy(CinderException):
    message = _("deleting volume %(volume_name)s that has snapshot")


class SnapshotIsBusy(CinderException):
    message = _("deleting snapshot %(snapshot_name)s that has "
                "dependent volumes")


class ISCSITargetNotFoundForVolume(NotFound):
    message = _("No target id found for volume %(volume_id)s.")


class InvalidImageRef(Invalid):
    message = _("Invalid image href %(image_href)s.")


class ImageNotFound(NotFound):
    message = _("Image %(image_id)s could not be found.")


class ServiceNotFound(NotFound):
    message = _("Service %(service_id)s could not be found.")


class HostNotFound(NotFound):
    message = _("Host %(host)s could not be found.")


class SchedulerHostFilterNotFound(NotFound):
    message = _("Scheduler Host Filter %(filter_name)s could not be found.")


class SchedulerHostWeigherNotFound(NotFound):
    message = _("Scheduler Host Weigher %(weigher_name)s could not be found.")


class HostBinaryNotFound(NotFound):
    message = _("Could not find binary %(binary)s on host %(host)s.")


class InvalidReservationExpiration(Invalid):
    message = _("Invalid reservation expiration %(expire)s.")


class InvalidQuotaValue(Invalid):
    message = _("Change would make usage less than 0 for the following "
                "resources: %(unders)s")


class QuotaNotFound(NotFound):
    message = _("Quota could not be found")


class QuotaResourceUnknown(QuotaNotFound):
    message = _("Unknown quota resources %(unknown)s.")


class ProjectQuotaNotFound(QuotaNotFound):
    message = _("Quota for project %(project_id)s could not be found.")


class QuotaClassNotFound(QuotaNotFound):
    message = _("Quota class %(class_name)s could not be found.")


class QuotaUsageNotFound(QuotaNotFound):
    message = _("Quota usage for project %(project_id)s could not be found.")


class ReservationNotFound(QuotaNotFound):
    message = _("Quota reservation %(uuid)s could not be found.")


class OverQuota(CinderException):
    message = _("Quota exceeded for resources: %(overs)s")


class MigrationNotFound(NotFound):
    message = _("Migration %(migration_id)s could not be found.")


class FileNotFound(NotFound):
    message = _("File %(file_path)s could not be found.")


#TODO(bcwaldon): EOL this exception!
class Duplicate(CinderException):
    pass


class VolumeTypeExists(Duplicate):
    message = _("Volume Type %(id)s already exists.")


class VolumeTypeEncryptionExists(Invalid):
    message = _("Volume type encryption for type %(type_id)s already exists.")


class MalformedRequestBody(CinderException):
    message = _("Malformed message body: %(reason)s")


class ConfigNotFound(NotFound):
    message = _("Could not find config at %(path)s")


class ParameterNotFound(NotFound):
    message = _("Could not find parameter %(param)s")


class PasteAppNotFound(NotFound):
    message = _("Could not load paste app '%(name)s' from %(path)s")


class NoValidHost(CinderException):
    message = _("No valid host was found. %(reason)s")


class NoMoreTargets(CinderException):
    """No more available targets."""
    pass


class WillNotSchedule(CinderException):
    message = _("Host %(host)s is not up or doesn't exist.")


class QuotaError(CinderException):
    message = _("Quota exceeded: code=%(code)s")
    code = 413
    headers = {'Retry-After': 0}
    safe = True


class VolumeSizeExceedsAvailableQuota(QuotaError):
    message = _("Requested volume or snapshot exceeds allowed Gigabytes "
                "quota. Requested %(requested)sG, quota is %(quota)sG and "
                "%(consumed)sG has been consumed.")


class VolumeLimitExceeded(QuotaError):
    message = _("Maximum number of volumes allowed (%(allowed)d) exceeded")


class SnapshotLimitExceeded(QuotaError):
    message = _("Maximum number of snapshots allowed (%(allowed)d) exceeded")


class DuplicateSfVolumeNames(Duplicate):
    message = _("Detected more than one volume with name %(vol_name)s")


class VolumeTypeCreateFailed(CinderException):
    message = _("Cannot create volume_type with "
                "name %(name)s and specs %(extra_specs)s")


class UnknownCmd(VolumeDriverException):
    message = _("Unknown or unsupported command %(cmd)s")


class MalformedResponse(VolumeDriverException):
    message = _("Malformed response to command %(cmd)s: %(reason)s")


class BadDriverResponseStatus(VolumeDriverException):
    message = _("Bad driver response status: %(status)s")


class FailedCmdWithDump(VolumeDriverException):
    message = _("Operation failed with status=%(status)s. Full dump: %(data)s")


class InstanceNotFound(NotFound):
    message = _("Instance %(instance_id)s could not be found.")


class GlanceMetadataExists(Invalid):
    message = _("Glance metadata cannot be updated, key %(key)s"
                " exists for volume id %(volume_id)s")


class GlanceMetadataNotFound(NotFound):
    message = _("Glance metadata for volume/snapshot %(id)s cannot be found.")


class ExportFailure(Invalid):
    message = _("Failed to export for volume: %(reason)s")


class MetadataCreateFailure(Invalid):
    message = _("Failed to create metadata for volume: %(reason)s")


class MetadataUpdateFailure(Invalid):
    message = _("Failed to update metadata for volume: %(reason)s")


class MetadataCopyFailure(Invalid):
    message = _("Failed to copy metadata to volume: %(reason)s")


class ImageCopyFailure(Invalid):
    message = _("Failed to copy image to volume: %(reason)s")


class BackupInvalidCephArgs(BackupDriverException):
    message = _("Invalid Ceph args provided for backup rbd operation")


class BackupOperationError(Invalid):
    message = _("An error has occurred during backup operation")


class BackupRBDOperationFailed(BackupDriverException):
    message = _("Backup RBD operation failed")


class BackupNotFound(NotFound):
    message = _("Backup %(backup_id)s could not be found.")


class BackupFailedToGetVolumeBackend(NotFound):
    message = _("Failed to identify volume backend.")


class InvalidBackup(Invalid):
    message = _("Invalid backup: %(reason)s")


class SwiftConnectionFailed(BackupDriverException):
    message = _("Connection to swift failed: %(reason)s")


class TransferNotFound(NotFound):
    message = _("Transfer %(transfer_id)s could not be found.")


class VolumeMigrationFailed(CinderException):
    message = _("Volume migration failed: %(reason)s")


class SSHInjectionThreat(CinderException):
    message = _("SSH command injection detected: %(command)s")


class QoSSpecsExists(Duplicate):
    message = _("QoS Specs %(specs_id)s already exists.")


class QoSSpecsCreateFailed(CinderException):
    message = _("Failed to create qos_specs: "
                "%(name)s with specs %(qos_specs)s.")


class QoSSpecsUpdateFailed(CinderException):
    message = _("Failed to update qos_specs: "
                "%(specs_id)s with specs %(qos_specs)s.")


class QoSSpecsNotFound(NotFound):
    message = _("No such QoS spec %(specs_id)s.")


class QoSSpecsAssociateFailed(CinderException):
    message = _("Failed to associate qos_specs: "
                "%(specs_id)s with type %(type_id)s.")


class QoSSpecsDisassociateFailed(CinderException):
    message = _("Failed to disassociate qos_specs: "
                "%(specs_id)s with type %(type_id)s.")


class QoSSpecsKeyNotFound(NotFound):
    message = _("QoS spec %(specs_id)s has no spec with "
                "key %(specs_key)s.")


class InvalidQoSSpecs(Invalid):
    message = _("Invalid qos specs: %(reason)s")


class QoSSpecsInUse(CinderException):
    message = _("QoS Specs %(specs_id)s is still associated with entities.")


class KeyManagerError(CinderException):
    msg_fmt = _("key manager error: %(reason)s")


class VolumeRetypeFailed(CinderException):
    message = _("Volume retype failed: %(reason)s")


# Driver specific exceptions
# Coraid
class CoraidException(VolumeDriverException):
    message = _('Coraid Cinder Driver exception.')


class CoraidJsonEncodeFailure(CoraidException):
    message = _('Failed to encode json data.')


class CoraidESMBadCredentials(CoraidException):
    message = _('Login on ESM failed.')


class CoraidESMReloginFailed(CoraidException):
    message = _('Relogin on ESM failed.')


class CoraidESMBadGroup(CoraidException):
    message = _('Group with name "%(group_name)s" not found.')


class CoraidESMConfigureError(CoraidException):
    message = _('ESM configure request failed: %(message)s.')


class CoraidESMNotAvailable(CoraidException):
    message = _('Coraid ESM not available with reason: %(reason)s.')


# Zadara
class ZadaraException(VolumeDriverException):
    message = _('Zadara Cinder Driver exception.')


class ZadaraServerCreateFailure(ZadaraException):
    message = _("Unable to create server object for initiator %(name)s")


class ZadaraServerNotFound(ZadaraException):
    message = _("Unable to find server object for initiator %(name)s")


class ZadaraVPSANoActiveController(ZadaraException):
    message = _("Unable to find any active VPSA controller")


class ZadaraAttachmentsNotFound(ZadaraException):
    message = _("Failed to retrieve attachments for volume %(name)s")


class ZadaraInvalidAttachmentInfo(ZadaraException):
    message = _("Invalid attachment info for volume %(name)s: %(reason)s")


class BadHTTPResponseStatus(ZadaraException):
    message = _("Bad HTTP response status %(status)s")


#SolidFire
class SolidFireAPIException(VolumeBackendAPIException):
    message = _("Bad response from SolidFire API")


class SolidFireDriverException(VolumeDriverException):
    message = _("SolidFire Cinder Driver exception")


class SolidFireAPIDataException(SolidFireAPIException):
    message = _("Error in SolidFire API response: data=%(data)s")


class SolidFireAccountNotFound(SolidFireDriverException):
    message = _("Unable to locate account %(account_name)s on "
                "Solidfire device")


class DuplicateSolidFireVolumeNames(SolidFireDriverException):
    message = _("Detected more than one volume with name %(vol_name)s")


# HP 3Par
class Invalid3PARDomain(VolumeDriverException):
    message = _("Invalid 3PAR Domain: %(err)s")


# NFS driver
class NfsException(VolumeDriverException):
    message = _("Unknown NFS exception")


class NfsNoSharesMounted(VolumeDriverException):
    message = _("No mounted NFS shares found")


class NfsNoSuitableShareFound(VolumeDriverException):
    message = _("There is no share which can host %(volume_size)sG")


# Gluster driver
class GlusterfsException(VolumeDriverException):
    message = _("Unknown Gluster exception")


class GlusterfsNoSharesMounted(VolumeDriverException):
    message = _("No mounted Gluster shares found")


class GlusterfsNoSuitableShareFound(VolumeDriverException):
    message = _("There is no share which can host %(volume_size)sG")
