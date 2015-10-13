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

from oslo_config import cfg
from oslo_log import log as logging
from oslo_versionedobjects import exception as obj_exc
import six
import webob.exc
from webob.util import status_generic_reasons
from webob.util import status_reasons

from cinder.i18n import _, _LE


LOG = logging.getLogger(__name__)

exc_log_opts = [
    cfg.BoolOpt('fatal_exception_format_errors',
                default=False,
                help='Make exception message format errors fatal.'),
]

CONF = cfg.CONF
CONF.register_opts(exc_log_opts)


class ConvertedException(webob.exc.WSGIHTTPException):
    def __init__(self, code=500, title="", explanation=""):
        self.code = code
        # There is a strict rule about constructing status line for HTTP:
        # '...Status-Line, consisting of the protocol version followed by a
        # numeric status code and its associated textual phrase, with each
        # element separated by SP characters'
        # (http://www.faqs.org/rfcs/rfc2616.html)
        # 'code' and 'title' can not be empty because they correspond
        # to numeric status code and its associated text
        if title:
            self.title = title
        else:
            try:
                self.title = status_reasons[self.code]
            except KeyError:
                generic_code = self.code // 100
                self.title = status_generic_reasons[generic_code]
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
        self.kwargs['message'] = message

        if 'code' not in self.kwargs:
            try:
                self.kwargs['code'] = self.code
            except AttributeError:
                pass

        for k, v in self.kwargs.items():
            if isinstance(v, Exception):
                self.kwargs[k] = six.text_type(v)

        if self._should_format():
            try:
                message = self.message % kwargs

            except Exception:
                exc_info = sys.exc_info()
                # kwargs doesn't match a variable in the message
                # log the issue and the kwargs
                LOG.exception(_LE('Exception in string format operation'))
                for name, value in kwargs.items():
                    LOG.error(_LE("%(name)s: %(value)s"),
                              {'name': name, 'value': value})
                if CONF.fatal_exception_format_errors:
                    six.reraise(*exc_info)
                # at least get the core message out if something happened
                message = self.message
        elif isinstance(message, Exception):
            message = six.text_type(message)

        # NOTE(luisg): We put the actual message in 'msg' so that we can access
        # it, because if we try to access the message via 'message' it will be
        # overshadowed by the class' message attribute
        self.msg = message
        super(CinderException, self).__init__(message)

    def _should_format(self):
        return self.kwargs['message'] is None or '%(message)' in self.message

    def __unicode__(self):
        return six.text_type(self.msg)


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


class APIException(CinderException):
    message = _("Error while requesting %(service)s API.")

    def __init__(self, message=None, **kwargs):
        if 'service' not in kwargs:
            kwargs['service'] = 'unknown'
        super(APIException, self).__init__(message, **kwargs)


class APITimeout(APIException):
    message = _("Timeout while requesting %(service)s API.")


class NotFound(CinderException):
    message = _("Resource could not be found.")
    code = 404
    safe = True


class VolumeNotFound(NotFound):
    message = _("Volume %(volume_id)s could not be found.")


class VolumeAttachmentNotFound(NotFound):
    message = _("Volume attachment could not be found with "
                "filter: %(filter)s .")


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


class VolumeTypeAccessNotFound(NotFound):
    message = _("Volume type access not found for %(volume_type_id)s / "
                "%(project_id)s combination.")


class VolumeTypeExtraSpecsNotFound(NotFound):
    message = _("Volume Type %(volume_type_id)s has no extra specs with "
                "key %(extra_specs_key)s.")


class VolumeTypeInUse(CinderException):
    message = _("Volume Type %(volume_type_id)s deletion is not allowed with "
                "volumes present with the type.")


class SnapshotNotFound(NotFound):
    message = _("Snapshot %(snapshot_id)s could not be found.")


class ServerNotFound(NotFound):
    message = _("Instance %(uuid)s could not be found.")


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


class FileNotFound(NotFound):
    message = _("File %(file_path)s could not be found.")


class Duplicate(CinderException):
    pass


class VolumeTypeExists(Duplicate):
    message = _("Volume Type %(id)s already exists.")


class VolumeTypeAccessExists(Duplicate):
    message = _("Volume type access for %(volume_type_id)s / "
                "%(project_id)s combination already exists.")


class VolumeTypeEncryptionExists(Invalid):
    message = _("Volume type encryption for type %(type_id)s already exists.")


class VolumeTypeEncryptionNotFound(NotFound):
    message = _("Volume type encryption for type %(type_id)s does not exist.")


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


class QuotaError(CinderException):
    message = _("Quota exceeded: code=%(code)s")
    code = 413
    headers = {'Retry-After': '0'}
    safe = True


class VolumeSizeExceedsAvailableQuota(QuotaError):
    message = _("Requested volume or snapshot exceeds allowed %(name)s "
                "quota. Requested %(requested)sG, quota is %(quota)sG and "
                "%(consumed)sG has been consumed.")

    def __init__(self, message=None, **kwargs):
        kwargs.setdefault('name', 'gigabytes')
        super(VolumeSizeExceedsAvailableQuota, self).__init__(
            message, **kwargs)


class VolumeSizeExceedsLimit(QuotaError):
    message = _("Requested volume size %(size)d is larger than "
                "maximum allowed limit %(limit)d.")


class VolumeBackupSizeExceedsAvailableQuota(QuotaError):
    message = _("Requested backup exceeds allowed Backup gigabytes "
                "quota. Requested %(requested)sG, quota is %(quota)sG and "
                "%(consumed)sG has been consumed.")


class VolumeLimitExceeded(QuotaError):
    message = _("Maximum number of volumes allowed (%(allowed)d) exceeded for "
                "quota '%(name)s'.")

    def __init__(self, message=None, **kwargs):
        kwargs.setdefault('name', 'volumes')
        super(VolumeLimitExceeded, self).__init__(message, **kwargs)


class SnapshotLimitExceeded(QuotaError):
    message = _("Maximum number of snapshots allowed (%(allowed)d) exceeded")


class BackupLimitExceeded(QuotaError):
    message = _("Maximum number of backups allowed (%(allowed)d) exceeded")


class DuplicateSfVolumeNames(Duplicate):
    message = _("Detected more than one volume with name %(vol_name)s")


class VolumeTypeCreateFailed(CinderException):
    message = _("Cannot create volume_type with "
                "name %(name)s and specs %(extra_specs)s")


class VolumeTypeUpdateFailed(CinderException):
    message = _("Cannot update volume_type %(id)s")


class UnknownCmd(VolumeDriverException):
    message = _("Unknown or unsupported command %(cmd)s")


class MalformedResponse(VolumeDriverException):
    message = _("Malformed response to command %(cmd)s: %(reason)s")


class FailedCmdWithDump(VolumeDriverException):
    message = _("Operation failed with status=%(status)s. Full dump: %(data)s")


class InvalidConnectorException(VolumeDriverException):
    message = _("Connector doesn't have required information: %(missing)s")


class GlanceMetadataExists(Invalid):
    message = _("Glance metadata cannot be updated, key %(key)s"
                " exists for volume id %(volume_id)s")


class GlanceMetadataNotFound(NotFound):
    message = _("Glance metadata for volume/snapshot %(id)s cannot be found.")


class ExportFailure(Invalid):
    message = _("Failed to export for volume: %(reason)s")


class RemoveExportException(VolumeDriverException):
    message = _("Failed to remove export for volume %(volume)s: %(reason)s")


class MetadataCreateFailure(Invalid):
    message = _("Failed to create metadata for volume: %(reason)s")


class MetadataUpdateFailure(Invalid):
    message = _("Failed to update metadata for volume: %(reason)s")


class MetadataCopyFailure(Invalid):
    message = _("Failed to copy metadata to volume: %(reason)s")


class InvalidMetadataType(Invalid):
    message = _("The type of metadata: %(metadata_type)s for volume/snapshot "
                "%(id)s is invalid.")


class ImageCopyFailure(Invalid):
    message = _("Failed to copy image to volume: %(reason)s")


class BackupInvalidCephArgs(BackupDriverException):
    message = _("Invalid Ceph args provided for backup rbd operation")


class BackupOperationError(Invalid):
    message = _("An error has occurred during backup operation")


class BackupMetadataUnsupportedVersion(BackupDriverException):
    message = _("Unsupported backup metadata version requested")


class BackupVerifyUnsupportedDriver(BackupDriverException):
    message = _("Unsupported backup verify driver")


class VolumeMetadataBackupExists(BackupDriverException):
    message = _("Metadata backup already exists for this volume")


class BackupRBDOperationFailed(BackupDriverException):
    message = _("Backup RBD operation failed")


class EncryptedBackupOperationFailed(BackupDriverException):
    message = _("Backup operation of an encrypted volume failed.")


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
    message = _("key manager error: %(reason)s")


class ManageExistingInvalidReference(CinderException):
    message = _("Manage existing volume failed due to invalid backend "
                "reference %(existing_ref)s: %(reason)s")


class ManageExistingAlreadyManaged(CinderException):
    message = _("Unable to manage existing volume. "
                "Volume %(volume_ref)s already managed.")


class ReplicationError(CinderException):
    message = _("Volume %(volume_id)s replication "
                "error: %(reason)s")


class ReplicationNotFound(NotFound):
    message = _("Volume replication for %(volume_id)s "
                "could not be found.")


class ManageExistingVolumeTypeMismatch(CinderException):
    message = _("Manage existing volume failed due to volume type mismatch: "
                "%(reason)s")


class ExtendVolumeError(CinderException):
    message = _("Error extending volume: %(reason)s")


class EvaluatorParseException(Exception):
    message = _("Error during evaluator parsing: %(reason)s")


UnsupportedObjectError = obj_exc.UnsupportedObjectError
OrphanedObjectError = obj_exc.OrphanedObjectError
IncompatibleObjectVersion = obj_exc.IncompatibleObjectVersion
ReadOnlyFieldError = obj_exc.ReadOnlyFieldError
ObjectActionError = obj_exc.ObjectActionError
ObjectFieldInvalid = obj_exc.ObjectFieldInvalid


class VolumeGroupNotFound(CinderException):
    message = _('Unable to find Volume Group: %(vg_name)s')


class VolumeGroupCreationFailed(CinderException):
    message = _('Failed to create Volume Group: %(vg_name)s')


class VolumeDeviceNotFound(CinderException):
    message = _('Volume device not found at %(device)s.')


# Driver specific exceptions
# Pure Storage
class PureDriverException(VolumeDriverException):
    message = _("Pure Storage Cinder driver failure: %(reason)s")


# SolidFire
class SolidFireAPIException(VolumeBackendAPIException):
    message = _("Bad response from SolidFire API")


class SolidFireDriverException(VolumeDriverException):
    message = _("SolidFire Cinder Driver exception")


class SolidFireAPIDataException(SolidFireAPIException):
    message = _("Error in SolidFire API response: data=%(data)s")


class SolidFireAccountNotFound(SolidFireDriverException):
    message = _("Unable to locate account %(account_name)s on "
                "Solidfire device")


class SolidFireRetryableException(VolumeBackendAPIException):
    message = _("Retryable SolidFire Exception encountered")


# HP 3Par
class Invalid3PARDomain(VolumeDriverException):
    message = _("Invalid 3PAR Domain: %(err)s")


# RemoteFS drivers
class RemoteFSException(VolumeDriverException):
    message = _("Unknown RemoteFS exception")


class RemoteFSNoSharesMounted(RemoteFSException):
    message = _("No mounted shares found")


class RemoteFSNoSuitableShareFound(RemoteFSException):
    message = _("There is no share which can host %(volume_size)sG")


# NFS driver
class NfsException(RemoteFSException):
    message = _("Unknown NFS exception")


class NfsNoSharesMounted(RemoteFSNoSharesMounted):
    message = _("No mounted NFS shares found")


class NfsNoSuitableShareFound(RemoteFSNoSuitableShareFound):
    message = _("There is no share which can host %(volume_size)sG")


# Smbfs driver
class SmbfsException(RemoteFSException):
    message = _("Unknown SMBFS exception.")


class SmbfsNoSharesMounted(RemoteFSNoSharesMounted):
    message = _("No mounted SMBFS shares found.")


class SmbfsNoSuitableShareFound(RemoteFSNoSuitableShareFound):
    message = _("There is no share which can host %(volume_size)sG.")


# Gluster driver
class GlusterfsException(RemoteFSException):
    message = _("Unknown Gluster exception")


class GlusterfsNoSharesMounted(RemoteFSNoSharesMounted):
    message = _("No mounted Gluster shares found")


class GlusterfsNoSuitableShareFound(RemoteFSNoSuitableShareFound):
    message = _("There is no share which can host %(volume_size)sG")


# Virtuozzo Storage Driver

class VzStorageException(RemoteFSException):
    message = _("Unknown Virtuozzo Storage exception")


class VzStorageNoSharesMounted(RemoteFSNoSharesMounted):
    message = _("No mounted Virtuozzo Storage shares found")


class VzStorageNoSuitableShareFound(RemoteFSNoSuitableShareFound):
    message = _("There is no share which can host %(volume_size)sG")


# Fibre Channel Zone Manager
class ZoneManagerException(CinderException):
    message = _("Fibre Channel connection control failure: %(reason)s")


class FCZoneDriverException(CinderException):
    message = _("Fibre Channel Zone operation failed: %(reason)s")


class FCSanLookupServiceException(CinderException):
    message = _("Fibre Channel SAN Lookup failure: %(reason)s")


class BrocadeZoningCliException(CinderException):
    message = _("Fibre Channel Zoning CLI error: %(reason)s")


class CiscoZoningCliException(CinderException):
    message = _("Fibre Channel Zoning CLI error: %(reason)s")


class NetAppDriverException(VolumeDriverException):
    message = _("NetApp Cinder Driver exception.")


class EMCVnxCLICmdError(VolumeBackendAPIException):
    message = _("EMC VNX Cinder Driver CLI exception: %(cmd)s "
                "(Return Code: %(rc)s) (Output: %(out)s).")


# ConsistencyGroup
class ConsistencyGroupNotFound(NotFound):
    message = _("ConsistencyGroup %(consistencygroup_id)s could not be found.")


class InvalidConsistencyGroup(Invalid):
    message = _("Invalid ConsistencyGroup: %(reason)s")


# CgSnapshot
class CgSnapshotNotFound(NotFound):
    message = _("CgSnapshot %(cgsnapshot_id)s could not be found.")


class InvalidCgSnapshot(Invalid):
    message = _("Invalid CgSnapshot: %(reason)s")


# Hitachi Block Storage Driver
class HBSDError(CinderException):
    message = _("HBSD error occurs.")


class HBSDCmdError(HBSDError):

    def __init__(self, message=None, ret=None, err=None):
        self.ret = ret
        self.stderr = err

        super(HBSDCmdError, self).__init__(message=message)


class HBSDBusy(HBSDError):
    message = "Device or resource is busy."


class HBSDNotFound(NotFound):
    message = _("Storage resource could not be found.")


class HBSDVolumeIsBusy(VolumeIsBusy):
    message = _("Volume %(volume_name)s is busy.")


# Datera driver
class DateraAPIException(VolumeBackendAPIException):
    message = _("Bad response from Datera API")


# Target drivers
class ISCSITargetCreateFailed(CinderException):
    message = _("Failed to create iscsi target for volume %(volume_id)s.")


class ISCSITargetRemoveFailed(CinderException):
    message = _("Failed to remove iscsi target for volume %(volume_id)s.")


class ISCSITargetAttachFailed(CinderException):
    message = _("Failed to attach iSCSI target for volume %(volume_id)s.")


class ISCSITargetDetachFailed(CinderException):
    message = _("Failed to detach iSCSI target for volume %(volume_id)s.")


class ISCSITargetHelperCommandFailed(CinderException):
    message = _("%(error_message)s")


# X-IO driver exception.
class XIODriverException(VolumeDriverException):
    message = _("X-IO Volume Driver exception!")


# Violin Memory drivers
class ViolinInvalidBackendConfig(CinderException):
    message = _("Volume backend config is invalid: %(reason)s")


class ViolinRequestRetryTimeout(CinderException):
    message = _("Backend service retry timeout hit: %(timeout)s sec")


class ViolinBackendErr(CinderException):
    message = _("Backend reports: %(message)s")


class ViolinBackendErrExists(CinderException):
    message = _("Backend reports: item already exists")


class ViolinBackendErrNotFound(CinderException):
    message = _("Backend reports: item not found")


# ZFSSA NFS driver exception.
class WebDAVClientError(CinderException):
    message = _("The WebDAV request failed. Reason: %(msg)s, "
                "Return code/reason: %(code)s, Source Volume: %(src)s, "
                "Destination Volume: %(dst)s, Method: %(method)s.")


# XtremIO Drivers
class XtremIOAlreadyMappedError(CinderException):
    message = _("Volume to Initiator Group mapping already exists")


class XtremIOArrayBusy(CinderException):
    message = _("System is busy, retry operation.")


# Infortrend EonStor DS Driver
class InfortrendCliException(CinderException):
    message = _("Infortrend CLI exception: %(err)s Param: %(param)s "
                "(Return Code: %(rc)s) (Output: %(out)s)")


# DOTHILL drivers
class DotHillInvalidBackend(CinderException):
    message = _("Backend doesn't exist (%(backend)s)")


class DotHillConnectionError(CinderException):
    message = _("%(message)s")


class DotHillAuthenticationError(CinderException):
    message = _("%(message)s")


class DotHillNotEnoughSpace(CinderException):
    message = _("Not enough space on backend (%(backend)s)")


class DotHillRequestError(CinderException):
    message = _("%(message)s")


class DotHillNotTargetPortal(CinderException):
    message = _("No active iSCSI portals with supplied iSCSI IPs")


# Sheepdog
class SheepdogError(VolumeBackendAPIException):
    message = _("An error has occured in SheepdogDriver. (Reason: %(reason)s)")


class SheepdogCmdError(SheepdogError):
    message = _("(Command: %(cmd)s) "
                "(Return Code: %(exit_code)s) "
                "(Stdout: %(stdout)s) "
                "(Stderr: %(stderr)s)")


class MetadataAbsent(CinderException):
    message = _("There is no metadata in DB object.")


class NotSupportedOperation(Invalid):
    message = _("Operation not supported: %(operation)s.")
    code = 405


# Hitachi HNAS drivers
class HNASConnError(CinderException):
    message = _("%(message)s")
