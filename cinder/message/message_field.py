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


class Action(object):

    SCHEDULE_ALLOCATE_VOLUME = ('001', _('schedule allocate volume'))
    ATTACH_VOLUME = ('002', _('attach volume'))
    COPY_VOLUME_TO_IMAGE = ('003', _('copy volume to image'))
    UPDATE_ATTACHMENT = ('004', _('update attachment'))
    COPY_IMAGE_TO_VOLUME = ('005', _('copy image to volume'))
    UNMANAGE_VOLUME = ('006', _('unmanage volume'))

    ALL = (SCHEDULE_ALLOCATE_VOLUME,
           ATTACH_VOLUME,
           COPY_VOLUME_TO_IMAGE,
           UPDATE_ATTACHMENT,
           COPY_IMAGE_TO_VOLUME,
           UNMANAGE_VOLUME
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

    ALL = (UNKNOWN_ERROR,
           DRIVER_NOT_INITIALIZED,
           NO_BACKEND_AVAILABLE,
           FAILED_TO_UPLOAD_VOLUME,
           VOLUME_ATTACH_MODE_INVALID,
           QUOTA_EXCEED,
           NOT_ENOUGH_SPACE_FOR_IMAGE,
           UNMANAGE_ENC_NOT_SUPPORTED,
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
        UNMANAGE_ENC_NOT_SUPPORTED: ['UnmanageEncVolNotSupported'],
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
    if exception is not None and isinstance(exception, Exception):
        for key, value in Detail.EXCEPTION_DETAIL_MAPPINGS.items():
            if exception.__class__.__name__ in value:
                return key[0]
    if detail in Detail.ALL:
        return detail[0]
    return Detail.UNKNOWN_ERROR[0]
