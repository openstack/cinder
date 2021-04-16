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

"""Message Resource, Action, Detail and user visible message.

Use Resource, Action and Detail's combination to indicate the Event
in the format of:

EVENT: VOLUME_RESOURCE_ACTION_DETAIL

Also, use exception-to-detail mapping to decrease the workload of
classifying event in cinder's task code.
"""

from cinder.i18n import _


class Resource(object):

    VOLUME = 'VOLUME'
    VOLUME_SNAPSHOT = 'VOLUME_SNAPSHOT'
    VOLUME_BACKUP = 'VOLUME_BACKUP'


class Action(object):

    SCHEDULE_ALLOCATE_VOLUME = ('001', _('schedule allocate volume'))
    ATTACH_VOLUME = ('002', _('attach volume'))
    COPY_VOLUME_TO_IMAGE = ('003', _('copy volume to image'))
    UPDATE_ATTACHMENT = ('004', _('update attachment'))
    COPY_IMAGE_TO_VOLUME = ('005', _('copy image to volume'))
    UNMANAGE_VOLUME = ('006', _('unmanage volume'))
    EXTEND_VOLUME = ('007', _('extend volume'))
    CREATE_VOLUME_FROM_BACKEND = ('008',
                                  _('create volume from backend storage'))
    SNAPSHOT_CREATE = ('009', _('create snapshot'))
    SNAPSHOT_DELETE = ('010', _('delete snapshot'))
    SNAPSHOT_UPDATE = ('011', _('update snapshot'))
    SNAPSHOT_METADATA_UPDATE = ('012', _('update snapshot metadata'))
    BACKUP_CREATE = ('013', _('create backup'))
    BACKUP_DELETE = ('014', _('delete backup'))
    BACKUP_RESTORE = ('015', _('restore backup'))

    ALL = (SCHEDULE_ALLOCATE_VOLUME,
           ATTACH_VOLUME,
           COPY_VOLUME_TO_IMAGE,
           UPDATE_ATTACHMENT,
           COPY_IMAGE_TO_VOLUME,
           UNMANAGE_VOLUME,
           EXTEND_VOLUME,
           CREATE_VOLUME_FROM_BACKEND,
           SNAPSHOT_CREATE,
           SNAPSHOT_DELETE,
           SNAPSHOT_UPDATE,
           SNAPSHOT_METADATA_UPDATE,
           BACKUP_CREATE,
           BACKUP_DELETE,
           BACKUP_RESTORE,
           )


class Detail(object):

    UNKNOWN_ERROR = ('001', _('An unknown error occurred.'))
    DRIVER_NOT_INITIALIZED = ('002',
                              _('Driver is not initialized at present.'))
    NO_BACKEND_AVAILABLE = ('003',
                            _('Could not find any available '
                              'weighted backend.'))
    FAILED_TO_UPLOAD_VOLUME = ('004',
                               _("Failed to upload volume to image "
                                 "at backend."))
    VOLUME_ATTACH_MODE_INVALID = ('005',
                                  _("Volume's attach mode is invalid."))
    QUOTA_EXCEED = ('006',
                    _("Not enough quota resource for operation."))
    NOT_ENOUGH_SPACE_FOR_IMAGE = ('007',
                                  _("Image used for creating volume exceeds "
                                    "available space."))
    UNMANAGE_ENC_NOT_SUPPORTED = (
        '008',
        _("Unmanaging encrypted volumes is not supported."))
    NOTIFY_COMPUTE_SERVICE_FAILED = (
        '009',
        _("Compute service failed to extend volume."))
    DRIVER_FAILED_EXTEND = (
        '010',
        _("Volume Driver failed to extend volume."))
    SIGNATURE_VERIFICATION_FAILED = (
        '011',
        _("Image signature verification failed."))
    DRIVER_FAILED_CREATE = (
        '012',
        _('Driver failed to create the volume.'))
    SNAPSHOT_CREATE_ERROR = ('013', _("Snapshot failed to create."))
    SNAPSHOT_UPDATE_METADATA_FAILED = (
        '014',
        _("Volume snapshot update metadata failed."))
    SNAPSHOT_IS_BUSY = ('015', _("Snapshot is busy."))
    SNAPSHOT_DELETE_ERROR = ('016', _("Snapshot failed to delete."))
    BACKUP_INVALID_STATE = ('017', _("Backup status is invalid."))
    BACKUP_SERVICE_DOWN = ('018', _("Backup service is down."))
    BACKUP_CREATE_DEVICE_ERROR = (
        '019', _("Failed to get backup device from the volume service."))
    BACKUP_CREATE_DRIVER_ERROR = (
        '020', ("Backup driver failed to create backup."))
    ATTACH_ERROR = ('021', _("Failed to attach volume."))
    DETACH_ERROR = ('022', _("Failed to detach volume."))
    BACKUP_CREATE_CLEANUP_ERROR = (
        '023', _("Cleanup of temporary volume/snapshot failed."))
    BACKUP_SCHEDULE_ERROR = (
        '024',
        ("Backup failed to schedule. Service not found for creating backup."))
    BACKUP_DELETE_DRIVER_ERROR = (
        '025', _("Backup driver failed to delete backup."))
    BACKUP_RESTORE_ERROR = (
        '026', _("Backup driver failed to restore backup."))
    VOLUME_INVALID_STATE = ('027', _("Volume status is invalid."))

    ALL = (UNKNOWN_ERROR,
           DRIVER_NOT_INITIALIZED,
           NO_BACKEND_AVAILABLE,
           FAILED_TO_UPLOAD_VOLUME,
           VOLUME_ATTACH_MODE_INVALID,
           QUOTA_EXCEED,
           NOT_ENOUGH_SPACE_FOR_IMAGE,
           UNMANAGE_ENC_NOT_SUPPORTED,
           NOTIFY_COMPUTE_SERVICE_FAILED,
           DRIVER_FAILED_EXTEND,
           SIGNATURE_VERIFICATION_FAILED,
           DRIVER_FAILED_CREATE,
           SNAPSHOT_CREATE_ERROR,
           SNAPSHOT_UPDATE_METADATA_FAILED,
           SNAPSHOT_IS_BUSY,
           SNAPSHOT_DELETE_ERROR,
           BACKUP_INVALID_STATE,
           BACKUP_SERVICE_DOWN,
           BACKUP_CREATE_DEVICE_ERROR,
           BACKUP_CREATE_DRIVER_ERROR,
           ATTACH_ERROR,
           DETACH_ERROR,
           BACKUP_CREATE_CLEANUP_ERROR,
           BACKUP_SCHEDULE_ERROR,
           BACKUP_DELETE_DRIVER_ERROR,
           BACKUP_RESTORE_ERROR,
           VOLUME_INVALID_STATE,
           )

    # Exception and detail mappings
    EXCEPTION_DETAIL_MAPPINGS = {
        DRIVER_NOT_INITIALIZED: ['DriverNotInitialized'],
        NO_BACKEND_AVAILABLE: ['NoValidBackend'],
        VOLUME_ATTACH_MODE_INVALID: ['InvalidVolumeAttachMode'],
        QUOTA_EXCEED: ['ImageLimitExceeded',
                       'BackupLimitExceeded',
                       'SnapshotLimitExceeded'],
        NOT_ENOUGH_SPACE_FOR_IMAGE: ['ImageTooBig'],
        SNAPSHOT_IS_BUSY: ['SnapshotIsBusy'],
    }


def translate_action(action_id):
    action_message = next((action[1] for action in Action.ALL
                           if action[0] == action_id), None)
    return action_message or 'unknown action'


def translate_detail(detail_id):
    detail_message = next((action[1] for action in Detail.ALL
                           if action[0] == detail_id), None)
    return detail_message or Detail.UNKNOWN_ERROR[1]


def translate_detail_id(exception, detail):
    """Get a detail_id to use for a message.

    If exception is in the EXCEPTION_DETAIL_MAPPINGS, returns the detail_id
    of the mapped Detail field.  If exception is not in the mapping or is None,
    returns the detail_id of the passed-in Detail field.  Otherwise, returns
    the detail_id of Detail.UNKNOWN_ERROR.

    :param exception: an Exception (or None)
    :param detail: a message_field.Detail field (or None)
    :returns: string
    :returns: the detail_id of a message_field.Detail field
    """
    if exception is not None and isinstance(exception, Exception):
        for key, value in Detail.EXCEPTION_DETAIL_MAPPINGS.items():
            if exception.__class__.__name__ in value:
                return key[0]
    if detail in Detail.ALL:
        return detail[0]
    return Detail.UNKNOWN_ERROR[0]
