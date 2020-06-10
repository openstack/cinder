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

from oslo_config import cfg
from oslo_log import log as logging
from oslo_versionedobjects import exception as obj_exc
import six
import webob.exc
from webob.util import status_generic_reasons
from webob.util import status_reasons

from cinder.i18n import _


LOG = logging.getLogger(__name__)

# TODO(smcginnis) Remove in Rocky
exc_log_opts = [
    cfg.BoolOpt('fatal_exception_format_errors',
                default=False,
                help='Make exception message format errors fatal.',
                deprecated_for_removal=True,
                deprecated_since='12.0.0',
                deprecated_reason='This is only used for internal testing.'),
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
                # NOTE(tommylikehu): If this is a cinder exception it will
                # return the msg object, so we won't be preventing
                # translations.
                self.kwargs[k] = six.text_type(v)

        if self._should_format():
            try:
                message = self.message % kwargs

            except Exception:
                # NOTE(melwitt): This is done in a separate method so it can be
                # monkey-patched during testing to make it a hard failure.
                self._log_exception()
                message = self.message
        elif isinstance(message, Exception):
            # NOTE(tommylikehu): If this is a cinder exception it will
            # return the msg object, so we won't be preventing
            # translations.
            message = six.text_type(message)

        # NOTE(luisg): We put the actual message in 'msg' so that we can access
        # it, because if we try to access the message via 'message' it will be
        # overshadowed by the class' message attribute
        self.msg = message
        super(CinderException, self).__init__(message)
        # Oslo.messaging use the argument 'message' to rebuild exception
        # directly at the rpc client side, therefore we should not use it
        # in our keyword arguments, otherwise, the rebuild process will fail
        # with duplicate keyword exception.
        self.kwargs.pop('message', None)

    def _log_exception(self):
        # kwargs doesn't match a variable in the message
        # log the issue and the kwargs
        LOG.exception('Exception in string format operation:')
        for name, value in self.kwargs.items():
            LOG.error("%(name)s: %(value)s",
                      {'name': name, 'value': value})

    def _should_format(self):
        return self.kwargs['message'] is None or '%(message)' in self.message

    # NOTE(tommylikehu): self.msg is already an unicode compatible object
    # as the __init__ method ensures of it, and we should not be modifying
    # it in any way with str(), unicode(), or six.text_type() as we would
    # be preventing translations from happening.
    def __unicode__(self):
        return self.msg


class VolumeBackendAPIException(CinderException):
    message = _("Bad or unexpected response from the storage volume "
                "backend API: %(data)s")


class VolumeDriverException(CinderException):
    message = _("Volume driver reported an error: %(message)s")


class BackupDriverException(CinderException):
    message = _("Backup driver reported an error: %(message)s")


class GlanceConnectionFailed(CinderException):
    message = _("Connection to glance failed: %(reason)s")


class ProgrammingError(CinderException):
    message = _('Programming error in Cinder: %(reason)s')


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


class InvalidAvailabilityZone(Invalid):
    message = _("Availability zone '%(az)s' is invalid.")


class InvalidVolumeType(Invalid):
    message = _("Invalid volume type: %(reason)s")


class InvalidGroupType(Invalid):
    message = _("Invalid group type: %(reason)s")


class InvalidVolume(Invalid):
    message = _("Invalid volume: %(reason)s")


class InvalidContentType(Invalid):
    message = _("Invalid content type %(content_type)s.")


class InvalidHost(Invalid):
    message = _("Invalid host: %(reason)s")


# Cannot be templated as the error syntax varies.
# msg needs to be constructed when raised.
class InvalidParameterValue(Invalid):
    message = "%(err)s"


class InvalidAuthKey(Invalid):
    message = _("Invalid auth key: %(reason)s")


class InvalidConfigurationValue(Invalid):
    message = _('Value "%(value)s" is not valid for '
                'configuration option "%(option)s"')


class ServiceUnavailable(Invalid):
    message = _("Service is unavailable at this time.")


class UnavailableDuringUpgrade(Invalid):
    message = _('Cannot perform %(action)s during system upgrade.')


class ImageUnacceptable(Invalid):
    message = _("Image %(image_id)s is unacceptable: %(reason)s")


class ImageTooBig(Invalid):
    message = _("Image %(image_id)s size exceeded available "
                "disk space: %(reason)s")


class DeviceUnavailable(Invalid):
    message = _("The device in the path %(path)s is unavailable: %(reason)s")


class SnapshotUnavailable(VolumeBackendAPIException):
    message = _("The snapshot is unavailable: %(data)s")


class InvalidUUID(Invalid):
    message = _("Expected a UUID but received %(uuid)s.")


class InvalidAPIVersionString(Invalid):
    message = _("API Version String %(version)s is of invalid format. Must "
                "be of format MajorNum.MinorNum.")


class VersionNotFoundForAPIMethod(Invalid):
    message = _("API version %(version)s is not supported on this method.")


class InvalidGlobalAPIVersion(Invalid):
    message = _("Version %(req_ver)s is not supported by the API. Minimum "
                "is %(min_ver)s and maximum is %(max_ver)s.")


class MissingRequired(Invalid):
    message = _("Missing required element '%(element)s' in request body.")


class ValidationError(Invalid):
    message = "%(detail)s"


class APIException(CinderException):
    message = _("Error while requesting %(service)s API.")

    def __init__(self, message=None, **kwargs):
        if 'service' not in kwargs:
            kwargs['service'] = 'unknown'
        super(APIException, self).__init__(message, **kwargs)


class APITimeout(APIException):
    message = _("Timeout while requesting %(service)s API.")


class RPCTimeout(CinderException):
    message = _("Timeout while requesting capabilities from backend "
                "%(service)s.")
    code = 502


class Duplicate(CinderException):
    pass


class NotFound(CinderException):
    message = _("Resource could not be found.")
    code = 404
    safe = True


class VolumeNotFound(NotFound):
    message = _("Volume %(volume_id)s could not be found.")


class MessageNotFound(NotFound):
    message = _("Message %(message_id)s could not be found.")


class VolumeAttachmentNotFound(NotFound):
    message = _("Volume attachment could not be found with "
                "filter: %(filter)s.")


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


class GroupTypeNotFound(NotFound):
    message = _("Group type %(group_type_id)s could not be found.")


class GroupTypeNotFoundByName(GroupTypeNotFound):
    message = _("Group type with name %(group_type_name)s "
                "could not be found.")


class GroupTypeAccessNotFound(NotFound):
    message = _("Group type access not found for %(group_type_id)s / "
                "%(project_id)s combination.")


class GroupTypeSpecsNotFound(NotFound):
    message = _("Group Type %(group_type_id)s has no specs with "
                "key %(group_specs_key)s.")


class GroupTypeInUse(CinderException):
    message = _("Group Type %(group_type_id)s deletion is not allowed with "
                "groups present with the type.")


class SnapshotNotFound(NotFound):
    message = _("Snapshot %(snapshot_id)s could not be found.")


class ServerNotFound(NotFound):
    message = _("Instance %(uuid)s could not be found.")


class VolumeSnapshotNotFound(NotFound):
    message = _("No snapshots found for volume %(volume_id)s.")


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

    def __init__(self, message=None, **kwargs):
        if not message:
            if kwargs.get('host', None):
                self.message = _("Service %(service_id)s could not be "
                                 "found on host %(host)s.")
            else:
                self.message = _("Service %(service_id)s could not be found.")
        super(ServiceNotFound, self).__init__(message, **kwargs)


class ServiceTooOld(Invalid):
    message = _("Service is too old to fulfil this request.")


class WorkerNotFound(NotFound):
    message = _("Worker with %s could not be found.")

    def __init__(self, message=None, **kwargs):
        keys_list = ('{0}=%({0})s'.format(key) for key in kwargs)
        placeholder = ', '.join(keys_list)
        self.message = self.message % placeholder
        super(WorkerNotFound, self).__init__(message, **kwargs)


class WorkerExists(Duplicate):
    message = _("Worker for %(type)s %(id)s already exists.")


class CleanableInUse(Invalid):
    message = _('%(type)s with id %(id)s is already being cleaned up or '
                'another host has taken over it.')


class ClusterNotFound(NotFound):
    message = _('Cluster %(id)s could not be found.')


class ClusterHasHosts(Invalid):
    message = _("Cluster %(id)s still has hosts.")


class ClusterExists(Duplicate):
    message = _("Cluster %(name)s already exists.")


class HostNotFound(NotFound):
    message = _("Host %(host)s could not be found.")


class SchedulerHostFilterNotFound(NotFound):
    message = _("Scheduler Host Filter %(filter_name)s could not be found.")


class SchedulerHostWeigherNotFound(NotFound):
    message = _("Scheduler Host Weigher %(weigher_name)s could not be found.")


class InvalidReservationExpiration(Invalid):
    message = _("Invalid reservation expiration %(expire)s.")


class InvalidQuotaValue(Invalid):
    message = _("Change would make usage less than 0 for the following "
                "resources: %(unders)s")


class InvalidNestedQuotaSetup(CinderException):
    message = _("Project quotas are not properly setup for nested quotas: "
                "%(reason)s.")


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


class VolumeTypeExists(Duplicate):
    message = _("Volume Type %(id)s already exists.")


class VolumeTypeAccessExists(Duplicate):
    message = _("Volume type access for %(volume_type_id)s / "
                "%(project_id)s combination already exists.")


class VolumeTypeEncryptionExists(Invalid):
    message = _("Volume type encryption for type %(type_id)s already exists.")


class VolumeTypeEncryptionNotFound(NotFound):
    message = _("Volume type encryption for type %(type_id)s does not exist.")


class GroupTypeExists(Duplicate):
    message = _("Group Type %(id)s already exists.")


class GroupTypeAccessExists(Duplicate):
    message = _("Group type access for %(group_type_id)s / "
                "%(project_id)s combination already exists.")


class GroupVolumeTypeMappingExists(Duplicate):
    message = _("Group volume type mapping for %(group_id)s / "
                "%(volume_type_id)s combination already exists.")


class GroupTypeEncryptionExists(Invalid):
    message = _("Group type encryption for type %(type_id)s already exists.")


class GroupTypeEncryptionNotFound(NotFound):
    message = _("Group type encryption for type %(type_id)s does not exist.")


class MalformedRequestBody(CinderException):
    message = _("Malformed message body: %(reason)s")


class ConfigNotFound(NotFound):
    message = _("Could not find config at %(path)s")


class ParameterNotFound(NotFound):
    message = _("Could not find parameter %(param)s")


class NoValidBackend(CinderException):
    message = _("No valid backend was found. %(reason)s")


class InvalidConnectionCapabilities(CinderException):
    message = _("Invalid connection capabilities. %(reason)s")


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
    message = _("Requested volume size %(size)dG is larger than "
                "maximum allowed limit %(limit)dG.")


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


class UnexpectedOverQuota(QuotaError):
    message = _("Unexpected over quota on %(name)s.")


class BackupLimitExceeded(QuotaError):
    message = _("Maximum number of backups allowed (%(allowed)d) exceeded")


class ImageLimitExceeded(QuotaError):
    message = _("Image quota exceeded")


class DuplicateSfVolumeNames(Duplicate):
    message = _("Detected more than one volume with name %(vol_name)s")


class VolumeTypeCreateFailed(CinderException):
    message = _("Cannot create volume_type with "
                "name %(name)s and specs %(extra_specs)s")


class VolumeTypeUpdateFailed(CinderException):
    message = _("Cannot update volume_type %(id)s")


class GroupTypeCreateFailed(CinderException):
    message = _("Cannot create group_type with "
                "name %(name)s and specs %(group_specs)s")


class GroupTypeUpdateFailed(CinderException):
    message = _("Cannot update group_type %(id)s")


class GroupLimitExceeded(QuotaError):
    message = _("Maximum number of groups allowed (%(allowed)d) exceeded")


class UnknownCmd(VolumeDriverException):
    message = _("Unknown or unsupported command %(cmd)s")


class MalformedResponse(VolumeDriverException):
    message = _("Malformed response to command %(cmd)s: %(reason)s")


class FailedCmdWithDump(VolumeDriverException):
    message = _("Operation failed with status=%(status)s. Full dump: %(data)s")


class InvalidConnectorException(VolumeDriverException):
    message = _("Connector doesn't have required information: %(missing)s")


class ConnectorRejected(VolumeDriverException):
    message = _("Connector can't be used with this driver anymore. %(reason)s")


class GlanceMetadataExists(Invalid):
    message = _("Glance metadata cannot be updated, key %(key)s"
                " exists for volume id %(volume_id)s")


class GlanceMetadataNotFound(NotFound):
    message = _("Glance metadata for volume/snapshot %(id)s cannot be found.")


class ImageDownloadFailed(CinderException):
    message = _("Failed to download image %(image_href)s, reason: %(reason)s")


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


class BackupMetadataNotFound(NotFound):
    message = _("Backup %(backup_id)s has no metadata with "
                "key %(metadata_key)s.")


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


class InvalidReplicationTarget(Invalid):
    message = _("Invalid Replication Target: %(reason)s")


class UnableToFailOver(CinderException):
    message = _("Unable to failover to replication target: %(reason)s).")


class ReplicationError(CinderException):
    message = _("Volume %(volume_id)s replication "
                "error: %(reason)s")


class ReplicationGroupError(CinderException):
    message = _("Group %(group_id)s replication "
                "error: %(reason)s.")


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


class LockCreationFailed(CinderException):
    message = _('Unable to create lock. Coordination backend not started.')


class LockingFailed(CinderException):
    message = _('Lock acquisition failed.')


UnsupportedObjectError = obj_exc.UnsupportedObjectError
OrphanedObjectError = obj_exc.OrphanedObjectError
IncompatibleObjectVersion = obj_exc.IncompatibleObjectVersion
ReadOnlyFieldError = obj_exc.ReadOnlyFieldError
ObjectActionError = obj_exc.ObjectActionError
ObjectFieldInvalid = obj_exc.ObjectFieldInvalid


class CappedVersionUnknown(CinderException):
    message = _("Unrecoverable Error: Versioned Objects in DB are capped to "
                "unknown version %(version)s. Most likely your environment "
                "contains only new services and you're trying to start an "
                "older one. Use `cinder-manage service list` to check that "
                "and upgrade this service.")


class VolumeGroupNotFound(CinderException):
    message = _('Unable to find Volume Group: %(vg_name)s')


class VolumeGroupCreationFailed(CinderException):
    message = _('Failed to create Volume Group: %(vg_name)s')


class VolumeNotDeactivated(CinderException):
    message = _('Volume %(name)s was not deactivated in time.')


class VolumeDeviceNotFound(CinderException):
    message = _('Volume device not found at %(device)s.')


# Driver specific exceptions
# Dell
class DellDriverRetryableException(VolumeBackendAPIException):
    message = _("Retryable Dell Exception encountered")


class DellDriverUnknownSpec(VolumeDriverException):
    message = _("Dell driver failure: %(reason)s")


# Pure Storage
class PureDriverException(VolumeDriverException):
    message = _("Pure Storage Cinder driver failure: %(reason)s")


class PureRetryableException(VolumeBackendAPIException):
    message = _("Retryable Pure Storage Exception encountered")


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


class RemoteFSConcurrentRequest(RemoteFSException):
    message = _("A concurrent, possibly contradictory, request "
                "has been made.")


class RemoteFSNoSharesMounted(RemoteFSException):
    message = _("No mounted shares found")


class RemoteFSNoSuitableShareFound(RemoteFSException):
    message = _("There is no share which can host %(volume_size)sG")


class RemoteFSInvalidBackingFile(VolumeDriverException):
    message = _("File %(path)s has invalid backing file %(backing_file)s.")


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


class ZoneManagerNotInitialized(CinderException):
    message = _("Fibre Channel Zone Manager not initialized")


class BrocadeZoningCliException(CinderException):
    message = _("Brocade Fibre Channel Zoning CLI error: %(reason)s")


class BrocadeZoningHttpException(CinderException):
    message = _("Brocade Fibre Channel Zoning HTTP error: %(reason)s")


class CiscoZoningCliException(CinderException):
    message = _("Cisco Fibre Channel Zoning CLI error: %(reason)s")


class NetAppDriverException(VolumeDriverException):
    message = _("NetApp Cinder Driver exception.")


class EMCVnxCLICmdError(VolumeBackendAPIException):
    message = _("EMC VNX Cinder Driver CLI exception: %(cmd)s "
                "(Return Code: %(rc)s) (Output: %(out)s).")


class EMCSPUnavailableException(EMCVnxCLICmdError):
    message = _("EMC VNX Cinder Driver SPUnavailableException: %(cmd)s "
                "(Return Code: %(rc)s) (Output: %(out)s).")


# ConsistencyGroup
class ConsistencyGroupNotFound(NotFound):
    message = _("ConsistencyGroup %(consistencygroup_id)s could not be found.")


class InvalidConsistencyGroup(Invalid):
    message = _("Invalid ConsistencyGroup: %(reason)s")


# Group
class GroupNotFound(NotFound):
    message = _("Group %(group_id)s could not be found.")


class InvalidGroup(Invalid):
    message = _("Invalid Group: %(reason)s")


class InvalidGroupStatus(Invalid):
    message = _("Invalid Group Status: %(reason)s")


# CgSnapshot
class CgSnapshotNotFound(NotFound):
    message = _("CgSnapshot %(cgsnapshot_id)s could not be found.")


class InvalidCgSnapshot(Invalid):
    message = _("Invalid CgSnapshot: %(reason)s")


# GroupSnapshot
class GroupSnapshotNotFound(NotFound):
    message = _("GroupSnapshot %(group_snapshot_id)s could not be found.")


class InvalidGroupSnapshot(Invalid):
    message = _("Invalid GroupSnapshot: %(reason)s")


class InvalidGroupSnapshotStatus(Invalid):
    message = _("Invalid GroupSnapshot Status: %(reason)s")


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


class TargetUpdateFailed(CinderException):
    message = _("Failed to update target for volume %(volume_id)s.")


class ISCSITargetHelperCommandFailed(CinderException):
    message = "%(error_message)s"


class BadHTTPResponseStatus(VolumeDriverException):
    message = _("Bad HTTP response status %(status)s")


class BadResetResourceStatus(CinderException):
    message = _("Bad reset resource status : %(message)s")


# ZADARA STORAGE VPSA driver exception
class ZadaraServerCreateFailure(VolumeDriverException):
    message = _("Unable to create server object for initiator %(name)s")


class ZadaraServerNotFound(NotFound):
    message = _("Unable to find server object for initiator %(name)s")


class ZadaraVPSANoActiveController(VolumeDriverException):
    message = _("Unable to find any active VPSA controller")


class ZadaraAttachmentsNotFound(NotFound):
    message = _("Failed to retrieve attachments for volume %(name)s")


class ZadaraInvalidAttachmentInfo(Invalid):
    message = _("Invalid attachment info for volume %(name)s: %(reason)s")


class ZadaraVolumeNotFound(VolumeDriverException):
    message = "%(reason)s"


# ZFSSA NFS driver exception.
class WebDAVClientError(VolumeDriverException):
    message = _("The WebDAV request failed. Reason: %(msg)s, "
                "Return code/reason: %(code)s, Source Volume: %(src)s, "
                "Destination Volume: %(dst)s, Method: %(method)s.")


# XtremIO Drivers
class XtremIOAlreadyMappedError(VolumeDriverException):
    message = _("Volume to Initiator Group mapping already exists")


class XtremIOArrayBusy(VolumeDriverException):
    message = _("System is busy, retry operation.")


class XtremIOSnapshotsLimitExceeded(VolumeDriverException):
    message = _("Exceeded the limit of snapshots per volume")


# StorPool driver
class StorPoolConfigurationInvalid(CinderException):
    message = _("Invalid parameter %(param)s in the %(section)s section "
                "of the /etc/storpool.conf file: %(error)s")


# DOTHILL drivers
class DotHillInvalidBackend(VolumeDriverException):
    message = _("Backend doesn't exist (%(backend)s)")


class DotHillConnectionError(VolumeDriverException):
    message = "%(message)s"


class DotHillAuthenticationError(VolumeDriverException):
    message = "%(message)s"


class DotHillNotEnoughSpace(VolumeDriverException):
    message = _("Not enough space on backend (%(backend)s)")


class DotHillRequestError(VolumeDriverException):
    message = "%(message)s"


class DotHillNotTargetPortal(VolumeDriverException):
    message = _("No active iSCSI portals with supplied iSCSI IPs")


class DotHillDriverNotSupported(VolumeDriverException):
    message = _("The Dot Hill driver is no longer supported.")


# Sheepdog
class SheepdogError(VolumeBackendAPIException):
    message = _("An error has occurred in SheepdogDriver. "
                "(Reason: %(reason)s)")


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


# NexentaStor driver exception
class NexentaException(VolumeDriverException):
    message = "%(message)s"


# Google Cloud Storage(GCS) backup driver
class GCSConnectionFailure(BackupDriverException):
    message = _("Google Cloud Storage connection failure: %(reason)s")


class GCSApiFailure(BackupDriverException):
    message = _("Google Cloud Storage api failure: %(reason)s")


class GCSOAuth2Failure(BackupDriverException):
    message = _("Google Cloud Storage oauth2 failure: %(reason)s")


# Kaminario K2
class KaminarioCinderDriverException(VolumeDriverException):
    message = _("KaminarioCinderDriver failure: %(reason)s")


class KaminarioRetryableException(VolumeDriverException):
    message = _("Kaminario retryable exception: %(reason)s")


# Synology driver
class SynoAPIHTTPError(VolumeDriverException):
    message = _("HTTP exit code: [%(code)s]")


class SynoAuthError(VolumeDriverException):
    message = _("Synology driver authentication failed: %(reason)s.")


class SynoLUNNotExist(VolumeDriverException):
    message = _("LUN not found by UUID: %(uuid)s.")


class AttachmentSpecsNotFound(NotFound):
    message = _("Attachment %(attachment_id)s has no "
                "key %(specs_key)s.")


class InvalidAttachment(Invalid):
    message = _("Invalid attachment: %(reason)s")


# Veritas driver
class UnableToExecuteHyperScaleCmd(VolumeDriverException):
    message = _("Failed HyperScale command for '%(message)s'")


class UnableToProcessHyperScaleCmdOutput(VolumeDriverException):
    message = _("Failed processing command output '%(cmd_out)s'"
                " for HyperScale command")


class ErrorInFetchingConfiguration(VolumeDriverException):
    message = _("Error in fetching configuration for '%(persona)s'")


class ErrorInSendingMsg(VolumeDriverException):
    message = _("Error in sending message '%(cmd_error)s'")


class ErrorInHyperScaleVersion(VolumeDriverException):
    message = _("Error in getting HyperScale version '%(cmd_error)s'")


class ErrorInParsingArguments(VolumeDriverException):
    message = _("Error in parsing message arguments : Invalid Payload")


# GPFS driver
class GPFSDriverUnsupportedOperation(VolumeBackendAPIException):
    message = _("GPFS driver unsupported operation: %(msg)s")


class InvalidName(Invalid):
    message = _("An invalid 'name' value was provided. %(reason)s")


class ServiceUserTokenNoAuth(CinderException):
    message = _("The [service_user] send_service_user_token option was "
                "requested, but no service auth could be loaded. Please check "
                "the [service_user] configuration section.")


class UnsupportedNVMETProtocol(Invalid):
    message = _("An invalid 'target_protocol' "
                "value was provided: %(protocol)s")


# NVMET driver
class NVMETTargetAddError(CinderException):
    message = "Failed to add subsystem: %(subsystem)s"


class NVMETTargetDeleteError(CinderException):
    message = "Failed to delete subsystem: %(subsystem)s"


class SnapshotLimitReached(CinderException):
    message = _("Exceeded the configured limit of "
                "%(set_limit)s snapshots per volume.")
