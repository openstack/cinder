# Copyright (C) 2020, 2024, Hitachi, Ltd.
# Copyright (C) 2025, 2026, Hitachi Vantara
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
"""Utility module for Hitachi HBSD Driver."""

import enum
import functools
import logging as base_logging
import threading
import typing

from oslo_log import log as logging
from oslo_utils import timeutils
from oslo_utils import units

from cinder import coordination
from cinder import exception
from cinder import utils as cinder_utils
from cinder.volume import volume_types

VERSION = '2.7.2'
CI_WIKI_NAME = 'Hitachi_CI'
PARAM_PREFIX = 'hitachi'
VENDOR_NAME = 'Hitachi'
DRIVER_DIR_NAME = 'hbsd'
DRIVER_PREFIX = 'HBSD'
DRIVER_FILE_PREFIX = 'hbsd'
TARGET_PREFIX = 'HBSD-'
HDP_VOL_ATTR = 'HDP'
HDT_VOL_ATTR = 'HDT'
DRS_VOL_ATTR = 'DRS'
VCP_VOL_ATTR = 'VCP'
VC_VOL_ATTR = 'VC'
NVOL_LDEV_TYPE = 'DP-VOL'
TARGET_IQN_SUFFIX = '.hbsd-target'
PAIR_ATTR = 'HTI'
MIRROR_ATTR = 'GAD'
REP_TYPE_ASYNC = 'UR'

GIGABYTE_PER_BLOCK_SIZE = units.Gi / 512

PRIMARY_STR = 'primary'
SECONDARY_STR = 'secondary'

NORMAL_LDEV_TYPE = 'Normal'

FULL = 'Full copy'
THIN = 'Thin copy'

INFO_SUFFIX = 'I'
WARNING_SUFFIX = 'W'
ERROR_SUFFIX = 'E'

PORT_ID_LENGTH = 5

BUSY_MESSAGE = "Device or resource is busy."

_QOS_MIN_UPPER_IOPS = 100
_QOS_MAX_UPPER_IOPS = 2147483647

_QOS_KEY_UPPER_IOPS = 'upperIops'
_QOS_KEY_LOWER_IOPS = 'lowerIops'
_QOS_KEY_UPPER_XFER_RATE = 'upperTransferRate'
_QOS_KEY_LOWER_XFER_RATE = 'lowerTransferRate'
_QOS_KEY_RESPONSE_PRIORITY = 'responsePriority'
_QOS_DYNAMIC_KEY_UPPER_IOPS_PER_GB = 'upperIopsPerGB'

QOS_KEYS = [_QOS_KEY_UPPER_IOPS, _QOS_KEY_UPPER_XFER_RATE,
            _QOS_KEY_LOWER_IOPS, _QOS_KEY_LOWER_XFER_RATE,
            _QOS_KEY_RESPONSE_PRIORITY]
QOS_DYNAMIC_KEYS = [_QOS_DYNAMIC_KEY_UPPER_IOPS_PER_GB]

# This map maps a dynamic value to the expected normal QoS value to use after
# the dynamic conversion.
QOS_DYNAMIC_KEY_MAP = {_QOS_DYNAMIC_KEY_UPPER_IOPS_PER_GB: _QOS_KEY_UPPER_IOPS}


@enum.unique
class HBSDMsg(enum.Enum):
    """messages for Hitachi HBSD Driver."""
    DRIVER_INITIALIZATION_START = {
        'msg_id': 4,
        'loglevel': base_logging.INFO,
        'msg': 'Initialization of %(driver)s %(version)s started.',
        'suffix': INFO_SUFFIX,
    }
    SET_CONFIG_VALUE = {
        'msg_id': 5,
        'loglevel': base_logging.INFO,
        'msg': 'Set %(object)s to %(value)s.',
        'suffix': INFO_SUFFIX,
    }
    OBJECT_CREATED = {
        'msg_id': 6,
        'loglevel': base_logging.INFO,
        'msg': 'Created %(object)s. (%(details)s)',
        'suffix': INFO_SUFFIX,
    }
    NO_LUN = {
        'msg_id': 301,
        'loglevel': base_logging.WARNING,
        'msg': 'A LUN (HLUN) was not found. (LDEV: %(ldev)s)',
        'suffix': WARNING_SUFFIX,
    }
    INVALID_LDEV_FOR_UNMAPPING = {
        'msg_id': 302,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to specify a logical device for the volume '
               '%(volume_id)s to be unmapped.',
        'suffix': WARNING_SUFFIX,
    }
    INVALID_LDEV_FOR_DELETION = {
        'msg_id': 304,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to specify a logical device to be deleted. '
               '(method: %(method)s, id: %(id)s)',
        'suffix': WARNING_SUFFIX,
    }
    DELETE_TARGET_FAILED = {
        'msg_id': 306,
        'loglevel': base_logging.WARNING,
        'msg': 'A host group or an iSCSI target could not be deleted. '
               '(port: %(port)s, gid: %(id)s)',
        'suffix': WARNING_SUFFIX,
    }
    CREATE_HOST_GROUP_FAILED = {
        'msg_id': 308,
        'loglevel': base_logging.WARNING,
        'msg': 'A host group could not be added. (port: %(port)s)',
        'suffix': WARNING_SUFFIX,
    }
    CREATE_ISCSI_TARGET_FAILED = {
        'msg_id': 309,
        'loglevel': base_logging.WARNING,
        'msg': 'An iSCSI target could not be added. (port: %(port)s)',
        'suffix': WARNING_SUFFIX,
    }
    UNMAP_LDEV_FAILED = {
        'msg_id': 310,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to unmap a logical device. (LDEV: %(ldev)s)',
        'suffix': WARNING_SUFFIX,
    }
    DELETE_LDEV_FAILED = {
        'msg_id': 313,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to delete a logical device. (LDEV: %(ldev)s)',
        'suffix': WARNING_SUFFIX,
    }
    MAP_LDEV_FAILED = {
        'msg_id': 314,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to map a logical device. (LDEV: %(ldev)s, port: '
               '%(port)s, id: %(id)s, lun: %(lun)s)',
        'suffix': WARNING_SUFFIX,
    }
    DISCARD_ZERO_PAGE_FAILED = {
        'msg_id': 315,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to perform a zero-page reclamation. (LDEV: '
               '%(ldev)s)',
        'suffix': WARNING_SUFFIX,
    }
    ADD_HBA_WWN_FAILED = {
        'msg_id': 317,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to assign the WWN. (port: %(port)s, gid: %(gid)s, '
               'wwn: %(wwn)s)',
        'suffix': WARNING_SUFFIX,
    }
    LDEV_NOT_EXIST = {
        'msg_id': 319,
        'loglevel': base_logging.WARNING,
        'msg': 'The logical device does not exist in the storage system. '
               '(LDEV: %(ldev)s)',
        'suffix': WARNING_SUFFIX,
    }
    REST_LOGIN_FAILED = {
        'msg_id': 321,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to perform user authentication of the REST API server. '
               '(user: %(user)s)',
        'suffix': WARNING_SUFFIX,
    }
    DELETE_PAIR_FAILED = {
        'msg_id': 325,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to delete copy pair. (P-VOL: %(pvol)s, S-VOL: '
               '%(svol)s)',
        'suffix': WARNING_SUFFIX,
    }
    DISCONNECT_VOLUME_FAILED = {
        'msg_id': 329,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to detach the logical device. (LDEV: %(ldev)s, '
               'reason: %(reason)s)',
        'suffix': WARNING_SUFFIX,
    }
    INVALID_EXTRA_SPEC_KEY_PORT = {
        'msg_id': 330,
        'loglevel': base_logging.WARNING,
        'msg': 'The port name specified for the extra spec key '
               '"%(target_ports_param)s" '
               'of the volume type is not specified for the '
               'target_ports or compute_target_ports '
               'parameter in cinder.conf. (port: %(port)s, volume type: '
               '%(volume_type)s)',
        'suffix': WARNING_SUFFIX,
    }
    VOLUME_IS_BEING_REHYDRATED = {
        'msg_id': 333,
        'loglevel': base_logging.WARNING,
        'msg': 'Retyping the volume will be performed using migration '
               'because the specified volume is being rehydrated. '
               'This process may take a long time depending on the data '
               'size. (volume: %(volume_id)s, volume type: %(volume_type)s)',
        'suffix': WARNING_SUFFIX,
    }
    INCONSISTENCY_DEDUPLICATION_SYSTEM_VOLUME = {
        'msg_id': 334,
        'loglevel': base_logging.WARNING,
        'msg': 'Retyping the volume will be performed using migration '
               'because inconsistency was found in the deduplication '
               'system data volume. This process may take a long time '
               'depending on the data size. '
               '(volume: %(volume_id)s, volume type: %(volume_type)s)',
        'suffix': WARNING_SUFFIX,
    }
    HOST_GROUP_NUMBER_IS_MAXIMUM = {
        'msg_id': 335,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to create the host group because the host group '
               'maximum of the port is exceeded. (port: %(port)s)',
        'suffix': WARNING_SUFFIX,
    }
    WWN_NUMBER_IS_MAXIMUM = {
        'msg_id': 336,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to add the wwns to the host group port because the '
               'WWN maximum of the port is exceeded. '
               '(port: %(port)s, WWN: %(wwn)s)',
        'suffix': WARNING_SUFFIX,
    }
    REPLICATION_VOLUME_OPERATION_FAILED = {
        'msg_id': 337,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to %(operation)s the %(type)s in a replication pair. '
               '(volume: %(volume_id)s, reason: %(reason)s)',
        'suffix': WARNING_SUFFIX,
    }
    SITE_INITIALIZATION_FAILED = {
        'msg_id': 338,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to initialize the driver for the %(site)s storage '
               'system.',
        'suffix': WARNING_SUFFIX,
    }
    INVALID_PORT = {
        'msg_id': 339,
        'loglevel': base_logging.WARNING,
        'msg': 'Port %(port)s will not be used because its settings are '
               'invalid. (%(additional_info)s)',
        'suffix': WARNING_SUFFIX,
    }
    INVALID_PORT_BY_ZONE_MANAGER = {
        'msg_id': 340,
        'loglevel': base_logging.WARNING,
        'msg': 'Port %(port)s will not be used because it is not considered '
               'to be active by the Fibre Channel Zone Manager.',
        'suffix': WARNING_SUFFIX,
    }
    NOT_LDEV_NUMBER_WARNING = {
        'msg_id': 341,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to %(operation)s. The LDEV number is not found in the '
               'Cinder object. (%(obj)s: %(obj_id)s)',
        'suffix': WARNING_SUFFIX,
    }
    COPY_PAIR_CANNOT_RETRIEVED = {
        'msg_id': 342,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to fail back a copy group. Copy pair information of '
               'the copy group cannot be retrieved. '
               '(copy group: %(copy_grp)s)',
        'suffix': WARNING_SUFFIX,
    }
    UNMANAGE_LDEV_EXIST_WARNING = {
        'msg_id': 343,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to fail back a copy group. An LDEV not managed by the '
               'backend exists in the copy group. (copy group: %(copy_grp)s, '
               'P-VOL: %(pvol)s, S-VOL: %(svol)s, config_group: '
               '%(config_group)s)',
        'suffix': WARNING_SUFFIX,
    }
    INVALID_COPY_GROUP_STATUS = {
        'msg_id': 344,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to fail back a copy group. The status of a pair in '
               'the copy group is invalid. (copy group: %(copy_grp)s, P-VOL: '
               '%(pvol)s, P-VOL status: %(pvol_status)s, S-VOL: %(svol)s, '
               'S-VOL status: %(svol_status)s)',
        'suffix': WARNING_SUFFIX,
    }
    FAILOVER_FAILBACK_WARNING = {
        'msg_id': 345,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to fail %(direction)s a %(obj)s. An error occurred '
               'during the %(operation)s. (%(obj)s: %(obj_id)s)',
        'suffix': WARNING_SUFFIX,
    }
    NOT_SYNCHRONIZED_WARNING = {
        'msg_id': 346,
        'loglevel': base_logging.WARNING,
        'msg': 'Volume data may not be up to date. P-VOL and S-VOL in the '
               'replication pair are not synchronized. (volume: %(volume)s, '
               'P-VOL: %(pvol)s, S-VOL: %(svol)s, S-VOL status: '
               '%(svol_status)s)',
        'suffix': WARNING_SUFFIX,
    }
    NOT_REPLICATION_PAIR_WARNING = {
        'msg_id': 347,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to fail over a volume. The LDEV for the volume is not '
               'in a remote replication pair. (volume: %(volume)s, LDEV: '
               '%(ldev)s)',
        'suffix': WARNING_SUFFIX,
    }
    SKIP_DELETING_LDEV = {
        'msg_id': 348,
        'loglevel': base_logging.WARNING,
        'msg': 'Skip deleting the LDEV and its LUNs and pairs because the '
               'LDEV is used by another object. (%(obj)s: %(obj_id)s, LDEV: '
               '%(ldev)s, LDEV label: %(ldev_label)s)',
        'suffix': WARNING_SUFFIX,
    }
    STORAGE_COMMAND_FAILED = {
        'msg_id': 600,
        'loglevel': base_logging.ERROR,
        'msg': 'The command %(cmd)s failed. (ret: %(ret)s, stdout: '
               '%(out)s, stderr: %(err)s)',
        'suffix': ERROR_SUFFIX,
    }
    INVALID_PARAMETER = {
        'msg_id': 601,
        'loglevel': base_logging.ERROR,
        'msg': 'A parameter is invalid. (%(param)s)',
        'suffix': ERROR_SUFFIX,
    }
    PAIR_STATUS_WAIT_TIMEOUT = {
        'msg_id': 611,
        'loglevel': base_logging.ERROR,
        'msg': 'The status change of copy pair could not be '
               'completed. (S-VOL: %(svol)s)',
        'suffix': ERROR_SUFFIX,
    }
    INVALID_LDEV_STATUS_FOR_COPY = {
        'msg_id': 612,
        'loglevel': base_logging.ERROR,
        'msg': 'The source logical device to be replicated does not exist '
               'in the storage system. (LDEV: %(ldev)s)',
        'suffix': ERROR_SUFFIX,
    }
    INVALID_LDEV_FOR_EXTENSION = {
        'msg_id': 613,
        'loglevel': base_logging.ERROR,
        'msg': 'The volume %(volume_id)s to be extended was not found.',
        'suffix': ERROR_SUFFIX,
    }
    NO_HBA_WWN_ADDED_TO_HOST_GRP = {
        'msg_id': 614,
        'loglevel': base_logging.ERROR,
        'msg': 'No WWN is assigned. (port: %(port)s, gid: %(gid)s)',
        'suffix': ERROR_SUFFIX,
    }
    UNABLE_TO_DELETE_PAIR = {
        'msg_id': 616,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to delete a pair. (P-VOL: %(pvol)s)',
        'suffix': ERROR_SUFFIX,
    }
    INVALID_VOLUME_TYPE_FOR_EXTEND = {
        'msg_id': 618,
        'loglevel': base_logging.ERROR,
        'msg': 'The volume %(volume_id)s could not be extended. The '
               'volume type must be Normal.',
        'suffix': ERROR_SUFFIX,
    }
    INVALID_LDEV_FOR_CONNECTION = {
        'msg_id': 619,
        'loglevel': base_logging.ERROR,
        'msg': 'The volume %(volume_id)s to be mapped was not found.',
        'suffix': ERROR_SUFFIX,
    }
    POOL_INFO_RETRIEVAL_FAILED = {
        'msg_id': 620,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to provide information about a pool. (pool: '
               '%(pool)s)',
        'suffix': ERROR_SUFFIX,
    }
    INVALID_LDEV_FOR_VOLUME_COPY = {
        'msg_id': 624,
        'loglevel': base_logging.ERROR,
        'msg': 'The %(type)s %(id)s source to be replicated was not '
               'found.',
        'suffix': ERROR_SUFFIX,
    }
    CONNECT_VOLUME_FAILED = {
        'msg_id': 634,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to attach the logical device. (LDEV: %(ldev)s, '
               'reason: %(reason)s)',
        'suffix': ERROR_SUFFIX,
    }
    CREATE_LDEV_FAILED = {
        'msg_id': 636,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to add the logical device.',
        'suffix': ERROR_SUFFIX,
    }
    PAIR_TARGET_FAILED = {
        'msg_id': 638,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to add the pair target.',
        'suffix': ERROR_SUFFIX,
    }
    MAP_PAIR_TARGET_FAILED = {
        'msg_id': 639,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to map a logical device to any pair targets. '
               '(LDEV: %(ldev)s)',
        'suffix': ERROR_SUFFIX,
    }
    POOL_NOT_FOUND = {
        'msg_id': 640,
        'loglevel': base_logging.ERROR,
        'msg': 'A pool could not be found. (pool: %(pool)s)',
        'suffix': ERROR_SUFFIX,
    }
    NO_AVAILABLE_RESOURCE = {
        'msg_id': 648,
        'loglevel': base_logging.ERROR,
        'msg': 'There are no resources available for use. (resource: '
               '%(resource)s)',
        'suffix': ERROR_SUFFIX,
    }
    NO_CONNECTED_TARGET = {
        'msg_id': 649,
        'loglevel': base_logging.ERROR,
        'msg': 'The host group or iSCSI target was not found.',
        'suffix': ERROR_SUFFIX,
    }
    RESOURCE_NOT_FOUND = {
        'msg_id': 650,
        'loglevel': base_logging.ERROR,
        'msg': 'The resource %(resource)s was not found.',
        'suffix': ERROR_SUFFIX,
    }
    LDEV_DELETION_WAIT_TIMEOUT = {
        'msg_id': 652,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to delete a logical device. (LDEV: %(ldev)s)',
        'suffix': ERROR_SUFFIX,
    }
    INVALID_LDEV_ATTR_FOR_MANAGE = {
        'msg_id': 702,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to manage the specified LDEV (%(ldev)s). The LDEV '
               'must be an unpaired %(ldevtype)s.',
        'suffix': ERROR_SUFFIX,
    }
    INVALID_LDEV_SIZE_FOR_MANAGE = {
        'msg_id': 703,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to manage the specified LDEV (%(ldev)s). The LDEV '
               'size must be expressed in gigabytes.',
        'suffix': ERROR_SUFFIX,
    }
    INVALID_LDEV_PORT_FOR_MANAGE = {
        'msg_id': 704,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to manage the specified LDEV (%(ldev)s). The LDEV '
               'must not be mapped.',
        'suffix': ERROR_SUFFIX,
    }
    INVALID_LDEV_TYPE_FOR_UNMANAGE = {
        'msg_id': 706,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to unmanage the volume %(volume_id)s. The volume '
               'type must be %(volume_type)s.',
        'suffix': ERROR_SUFFIX,
    }
    INVALID_LDEV_FOR_MANAGE = {
        'msg_id': 707,
        'loglevel': base_logging.ERROR,
        'msg': 'No valid value is specified for "source-id" or "source-name". '
               'A valid LDEV number must be specified in "source-id" or '
               'a valid LDEV name must be specified in "source-name" '
               'to manage the volume.',
        'suffix': ERROR_SUFFIX,
    }
    FAILED_CREATE_CTG_SNAPSHOT = {
        'msg_id': 712,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to create a consistency group snapshot. '
               'The number of pairs in the consistency group or the number of '
               'consistency group snapshots has reached the limit.',
        'suffix': ERROR_SUFFIX,
    }
    LDEV_NOT_EXIST_FOR_ADD_GROUP = {
        'msg_id': 716,
        'loglevel': base_logging.ERROR,
        'msg': 'No logical device exists in the storage system for the volume '
               '%(volume_id)s to be added to the %(group)s %(group_id)s.',
        'suffix': ERROR_SUFFIX,
    }
    SNAPSHOT_UNMANAGE_FAILED = {
        'msg_id': 722,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to unmanage the snapshot %(snapshot_id)s. '
               'This driver does not support unmanaging snapshots.',
        'suffix': ERROR_SUFFIX,
    }
    INVALID_EXTRA_SPEC_KEY = {
        'msg_id': 723,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to create a volume. '
               'An invalid value is specified for the extra spec key '
               '"%(key)s" of the volume type. (value: %(value)s)',
        'suffix': ERROR_SUFFIX,
    }
    VOLUME_COPY_FAILED = {
        'msg_id': 725,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to copy a volume. (P-VOL: %(pvol)s, S-VOL: %(svol)s)',
        'suffix': ERROR_SUFFIX
    }
    CONSISTENCY_NOT_GUARANTEE = {
        'msg_id': 726,
        'loglevel': base_logging.ERROR,
        'msg': 'A volume or snapshot cannot be deleted. '
               'The consistency of logical device for '
               'a volume or snapshot cannot be guaranteed. (LDEV: %(ldev)s)',
        'suffix': ERROR_SUFFIX
    }
    FAILED_CHANGE_VOLUME_TYPE = {
        'msg_id': 727,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to change a volume type. '
               'An invalid value is specified for the extra spec key '
               '"%(key)s" of the volume type after change. '
               '(value: %(value)s)',
        'suffix': ERROR_SUFFIX
    }
    NOT_COMPLETED_CHANGE_VOLUME_TYPE = {
        'msg_id': 728,
        'loglevel': base_logging.ERROR,
        'msg': 'The volume type change could not be completed. '
               '(LDEV: %(ldev)s)',
        'suffix': ERROR_SUFFIX
    }
    REST_SERVER_CONNECT_FAILED = {
        'msg_id': 731,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to communicate with the REST API server. '
               '(exception: %(exception)s, message: %(message)s, '
               'method: %(method)s, url: %(url)s, params: %(params)s, '
               'body: %(body)s)',
        'suffix': ERROR_SUFFIX,
    }
    REST_API_FAILED = {
        'msg_id': 732,
        'loglevel': base_logging.ERROR,
        'msg': 'The REST API failed. (source: %(errorSource)s, '
               'ID: %(messageId)s, message: %(message)s, cause: %(cause)s, '
               'solution: %(solution)s, code: %(errorCode)s, '
               'method: %(method)s, url: %(url)s, params: %(params)s, '
               'body: %(body)s)',
        'suffix': ERROR_SUFFIX,
    }
    REST_API_TIMEOUT = {
        'msg_id': 733,
        'loglevel': base_logging.ERROR,
        'msg': 'The REST API timed out. (job ID: %(job_id)s, '
               'job status: %(status)s, job state: %(state)s, '
               'method: %(method)s, url: %(url)s, params: %(params)s, '
               'body: %(body)s)',
        'suffix': ERROR_SUFFIX,
    }
    REST_API_HTTP_ERROR = {
        'msg_id': 734,
        'loglevel': base_logging.ERROR,
        'msg': 'The REST API failed. (HTTP status code: %(status_code)s, '
               'response body: %(response_body)s, '
               'method: %(method)s, url: %(url)s, params: %(params)s, '
               'body: %(body)s)',
        'suffix': ERROR_SUFFIX,
    }
    GROUP_OBJECT_DELETE_FAILED = {
        'msg_id': 736,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to delete a %(obj)s in a %(group)s. (%(group)s: '
               '%(group_id)s, %(obj)s: %(obj_id)s, LDEV: %(ldev)s, reason: '
               '%(reason)s)',
        'suffix': ERROR_SUFFIX,
    }
    GROUP_SNAPSHOT_CREATE_FAILED = {
        'msg_id': 737,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to create a volume snapshot in a group snapshot that '
               'does not guarantee consistency. (group: %(group)s, '
               'group snapshot: %(group_snapshot)s, group type: '
               '%(group_type)s, volume: %(volume)s, snapshot: %(snapshot)s)',
        'suffix': ERROR_SUFFIX,
    }
    NO_ACTIVE_WWN = {
        'msg_id': 747,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to initialize volume connection because no active WWN '
               'was found for the connector. (WWN: %(wwn)s, volume: %(volume)s'
               ')',
        'suffix': ERROR_SUFFIX,
    }
    NO_PORT_WITH_ACTIVE_WWN = {
        'msg_id': 748,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to initialize volume connection because no port with '
               'an active WWN was found. (%(port_wwns)s, volume: %(volume)s)',
        'suffix': ERROR_SUFFIX,
    }
    ZONE_MANAGER_IS_NOT_AVAILABLE = {
        'msg_id': 749,
        'loglevel': base_logging.ERROR,
        'msg': 'The Fibre Channel Zone Manager is not available. The Fibre '
               'Channel Zone Manager must be up and running when '
               'port_scheduler parameter is set to True.',
        'suffix': ERROR_SUFFIX,
    }
    HOST_GROUP_OR_WWN_IS_NOT_AVAILABLE = {
        'msg_id': 750,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to initialize volume connection because no available '
               'resource of host group or wwn was found. (ports: %(ports)s)',
        'suffix': ERROR_SUFFIX,
    }
    SITE_NOT_INITIALIZED = {
        'msg_id': 751,
        'loglevel': base_logging.ERROR,
        'msg': 'The driver is not initialized for the %(site)s storage '
               'system.',
        'suffix': ERROR_SUFFIX,
    }
    CREATE_REPLICATION_VOLUME_FAILED = {
        'msg_id': 752,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to create the %(type)s for a %(rep_type)s pair. '
               '(volume: %(volume_id)s, volume type: %(volume_type)s, '
               'size: %(size)s)',
        'suffix': ERROR_SUFFIX,
    }
    CREATE_REPLICATION_PAIR_FAILED = {
        'msg_id': 754,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to create a %(rep_type)s pair or '
               'to mirror data in a %(rep_type)s pair. '
               '(P-VOL: %(pvol)s, S-VOL: %(svol)s, copy group: '
               '%(copy_group)s, pair status: %(status)s)',
        'suffix': ERROR_SUFFIX,
    }
    SPLIT_REPLICATION_PAIR_FAILED = {
        'msg_id': 755,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to split a %(rep_type)s pair. '
               '(P-VOL: %(pvol)s, S-VOL: %(svol)s, '
               'copy group: %(copy_group)s, pair status: %(status)s)',
        'suffix': ERROR_SUFFIX,
    }
    PAIR_CHANGE_TIMEOUT = {
        'msg_id': 756,
        'loglevel': base_logging.ERROR,
        'msg': 'A timeout occurred before the status of '
               'the %(rep_type)s pair changes. '
               '(P-VOL: %(pvol)s, S-VOL: %(svol)s, copy group: '
               '%(copy_group)s, current status: %(current_status)s, '
               'expected status: %(expected_status)s, timeout: %(timeout)s '
               'seconds)',
        'suffix': ERROR_SUFFIX,
    }
    EXTEND_REPLICATION_VOLUME_ERROR = {
        'msg_id': 758,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to extend a volume. The LDEVs for the volume are in '
               'a %(rep_type)s pair and the volume is attached. '
               '(volume: %(volume_id)s, '
               'LDEV: %(ldev)s, source size: %(source_size)s, destination '
               'size: %(destination_size)s, P-VOL: %(pvol)s, S-VOL: %(svol)s, '
               'P-VOL[numOfPorts]: %(pvol_num_of_ports)s, '
               'S-VOL[numOfPorts]: %(svol_num_of_ports)s)',
        'suffix': ERROR_SUFFIX,
    }
    REPLICATION_VOLUME_ADD_GROUP_ERROR = {
        'msg_id': 759,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to add a volume to a group. '
               'The LDEVs for the volume are in a %(rep_type)s pair. '
               '(volume: %(volume_id)s, LDEV: %(ldev)s, group: %(group_id)s)',
        'suffix': ERROR_SUFFIX,
    }
    MIGRATE_VOLUME_FAILED = {
        'msg_id': 760,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to migrate a volume. The volume is in a copy pair that '
               'cannot be deleted. (volume: %(volume)s, LDEV: %(ldev)s, '
               '(P-VOL, S-VOL, copy method, status): %(pair_info)s)',
        'suffix': ERROR_SUFFIX,
    }
    DRIVER_INITIALIZE_FAILED = {
        'msg_id': 762,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to initialize the driver. The same parameter is '
               'specified more than once in cinder.conf. '
               '(config_group: %(config_group)s, parameter: %(param)s)',
        'suffix': ERROR_SUFFIX,
    }
    FAILED_FAILBACK = {
        'msg_id': 763,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to fail back the driver. Initialization of the driver '
               'for the %(site)s storage system failed.',
        'suffix': ERROR_SUFFIX,
    }
    INVALID_DESTINATION = {
        'msg_id': 764,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to fail %(direction)s the driver. The specified '
               'fail%(direction)s destination is invalid. '
               '(execution site: %(execution_site)s, specified backend_id: '
               '%(specified_backend_id)s, defined backend_id: '
               '%(defined_backend_id)s)',
        'suffix': ERROR_SUFFIX,
    }
    MANAGE_REPLICATION_VOLUME_ERROR = {
        'msg_id': 765,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to manage a volume. The volume type extra spec '
               '"replication_enabled" is set to "%(replication_enabled)s". '
               '(source-id: %(source_id)s, volume: %(volume)s, volume type: '
               '%(volume_type)s)',
        'suffix': ERROR_SUFFIX,
    }
    REPLICATION_PAIR_ERROR = {
        'msg_id': 766,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to %(operation)s. The LDEV for the volume is in '
               'a remote replication pair. (volume: %(volume)s, '
               '%(snapshot_info)sLDEV: %(ldev)s)',
        'suffix': ERROR_SUFFIX,
    }
    OTHER_SITE_ERROR = {
        'msg_id': 767,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to %(operation)s. The LDEV for the %(obj)s exists in '
               'the other site. (execution site: %(execution_site)s, '
               'LDEV site: %(ldev_site)s, %(group_info)s%(obj)s: %(obj_id)s, '
               'LDEV: %(ldev)s)',
        'suffix': ERROR_SUFFIX,
    }
    COPY_GROUP_CANNOT_RETRIEVED = {
        'msg_id': 768,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to fail back the backend. Copy group list information '
               'cannot be retrieved. (config_group: %(config_group)s)',
        'suffix': ERROR_SUFFIX,
    }
    CREATE_JOURNAL_FAILED = {
        'msg_id': 769,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to create a journal for remote replication. No journal '
               'ID is available. (volume: %(volume)s)',
        'suffix': ERROR_SUFFIX,
    }
    LDEV_NUMBER_NOT_FOUND = {
        'msg_id': 770,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to %(operation)s. The LDEV number is not found in the '
               'Cinder object. (%(obj)s: %(obj_id)s)',
        'suffix': ERROR_SUFFIX,
    }
    REPLICATION_AND_GROUP_ERROR = {
        'msg_id': 771,
        'loglevel': base_logging.ERROR,
        'msg': ('Failed to %(operation)s. Remote replication and '
                'generic volume group cannot be applied to the same volume. '
                '(volume: %(volume)s, group: %(group)s)'),
        'suffix': ERROR_SUFFIX,
    }
    GET_SNAPSHOT_FROM_SVOL_FAILURE = {
        'msg_id': 772,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to get snapshot from s-vol %(svol)s. ',
        'suffix': ERROR_SUFFIX,
    }
    VCLONE_PAIR_FAILED = {
        'msg_id': 773,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to ss2vclone. p-vol=%(pvol)s,s-vol=%(svol)s',
        'suffix': ERROR_SUFFIX,
    }

    def __init__(self, error_info):
        """Initialize Enum attributes."""
        self.msg_id = error_info['msg_id']
        self.level = error_info['loglevel']
        self.msg = error_info['msg']
        self.suffix = error_info['suffix']

    def output_log(self, storage_id, **kwargs):
        """Output the message to the log file and return the message."""
        msg = self.msg % kwargs
        if storage_id:
            LOG.log(
                self.level,
                "%(storage_id)s MSGID%(msg_id)04d-%(msg_suffix)s: %(msg)s",
                {'storage_id': storage_id[-6:], 'msg_id': self.msg_id,
                 'msg_suffix': self.suffix, 'msg': msg})
        else:
            LOG.log(
                self.level, "MSGID%(msg_id)04d-%(msg_suffix)s: %(msg)s",
                {'msg_id': self.msg_id, 'msg_suffix': self.suffix, 'msg': msg})
        return msg


def output_log(msg_enum, storage_id=None, **kwargs):
    """Output the specified message to the log file and return the message."""
    return msg_enum.output_log(storage_id, **kwargs)


LOG = logging.getLogger(__name__)
MSG = HBSDMsg


def timed_out(start_time, timeout):
    """Check if the specified time has passed."""
    return timeutils.is_older_than(start_time, timeout)


def build_initiator_target_map(connector, target_wwns, lookup_service):
    """Return a dictionary mapping server-wwns and lists of storage-wwns."""
    init_targ_map = {}
    initiator_wwns = connector['wwpns']
    if lookup_service:
        dev_map = lookup_service.get_device_mapping_from_network(
            initiator_wwns, target_wwns)
        for fabric_name in dev_map:
            fabric = dev_map[fabric_name]
            for initiator in fabric['initiator_port_wwn_list']:
                init_targ_map[initiator] = fabric['target_port_wwn_list']
    else:
        for initiator in initiator_wwns:
            init_targ_map[initiator] = target_wwns
    return init_targ_map


def safe_get_err_code(errobj):
    if not errobj:
        return '', ''
    err_code = errobj.get('errorCode', {})
    return err_code.get('SSB1', '').upper(), err_code.get('SSB2', '').upper()


def safe_get_return_code(errobj):
    if not errobj:
        return ''
    err_code = errobj.get('errorCode', {})
    return err_code.get('errorCode', '')


def safe_get_message_id(errobj):
    if not errobj:
        return ''
    return errobj.get('messageId', '')


def safe_get_message(errobj):
    if not errobj:
        return ''
    return errobj.get('message', '')


def is_shared_connection(volume, connector):
    """Check if volume is multiattach to 1 node."""
    connection_count = 0
    host = connector.get('host') if connector else None
    if host and volume.get('multiattach'):
        attachment_list = volume.volume_attachment
        try:
            att_list = attachment_list.object
        except AttributeError:
            att_list = attachment_list
        for attachment in att_list:
            if attachment.attached_host == host:
                connection_count += 1
    return connection_count > 1


def cleanup_cg_in_volume(volume):
    if ('group_id' in volume and volume.group_id and
            'consistencygroup_id' in volume and
            volume.consistencygroup_id):
        volume.consistencygroup_id = None
        if 'consistencygroup' in volume:
            volume.consistencygroup = None


def get_exception_msg(exc):
    if exc.args:
        return exc.msg if isinstance(
            exc, exception.CinderException) else exc.args[0]
    else:
        return ""


def synchronized_on_copy_group():
    def wrap(func):
        @functools.wraps(func)
        def inner(self, remote_client, copy_group_name, *args, **kwargs):
            sync_key = '%s-%s' % (copy_group_name,
                                  self.storage_id[-6:])

            @cinder_utils.synchronized(sync_key, external=True)
            def _inner():
                return func(self, remote_client, copy_group_name,
                            *args, **kwargs)
            return _inner()
        return inner
    return wrap


def get_qos_specs_from_volume(target, check_volume_size=None):
    """Return a dictionary of the QoS specs of the target.

    :param target: Volume or Snapshot whose QoS specs are queried.
    :type target: Volume or Snapshot
    :param check_volume_size: A volume size to query for the given
    target (use to check resize values)
    :type check_volume_size: NoneType to use target, long to check
    alternate value
    :return: QoS specs.
    :rtype: dict
    """

    # If the target is a Volume, volume_type is volume.volume_type.
    # If the target is a Snapshot, volume_type is snapshot.volume.volume_type.
    # We combine these into "getattr(target, 'volume', target).volume_type)".
    # We do the same for the size element.

    use_size = check_volume_size
    if use_size is None:
        use_size = getattr(target, 'volume', target).size

    return get_qos_specs_from_volume_type_and_size(
        getattr(target, 'volume', target).volume_type,
        use_size)


def _get_qos_dynamic_value(key, value, volume_size, qos_specs):

    if key == _QOS_DYNAMIC_KEY_UPPER_IOPS_PER_GB:

        min_upper_iops = _QOS_MIN_UPPER_IOPS
        max_upper_iops = _QOS_MAX_UPPER_IOPS
        if _QOS_KEY_LOWER_IOPS in qos_specs:
            min_upper_iops = int(qos_specs[_QOS_KEY_LOWER_IOPS]) + 1
        if _QOS_KEY_UPPER_IOPS in qos_specs:
            max_upper_iops = int(qos_specs[_QOS_KEY_UPPER_IOPS])

        upperIops = int(volume_size) * int(value)
        if upperIops < min_upper_iops:
            upperIops = min_upper_iops
        if upperIops > max_upper_iops:
            upperIops = max_upper_iops

        return upperIops

    # We should not get here normally.
    return None


def get_qos_specs_from_volume_type_and_size(volume_type, size):
    """Return a dictionary of the QoS specs of the volume_type.

    :param volume_type: VolumeType whose QoS specs are queried. This must not
    be None.
    :type volume_type: VolumeType
    :param size: The size of the volume whose QoS specs are queried for
    adaptive QoS.
    :type size: long
    :return: QoS specs.
    :rtype: dict
    The following is an example of the returned value:
    {'lowerTransferRate': 7,
     'responsePriority': 2,
     'upperIops': 456}
    """
    qos = {}
    specs = volume_types.get_volume_type_qos_specs(volume_type.id)['qos_specs']
    # The following is an example of the specs:
    # {'consumer': 'back-end',
    #  'created_at': datetime.datetime(2024, 9, 2, 3, 11, 1),
    #  'id': '81058c04-06eb-49d7-9199-7016785bf386',
    #  'name': 'qos1',
    #  'specs': {'lowerTransferRate': '7',
    #            'responsePriority': '2',
    #            'upperIops': '456'}}
    if specs is None:
        return qos
    if 'consumer' in specs and specs['consumer'] not in ('back-end', 'both'):
        return qos

    # First pass is for normal keys.
    for key in specs['specs'].keys():
        if key in QOS_KEYS:
            if specs['specs'][key].isdigit():
                qos[key] = int(specs['specs'][key])
            else:
                qos[key] = specs['specs'][key]

    # We do a second pass for dynamic keys as they may have to overwrite
    # values from the standard QoS keys.
    for key in specs['specs'].keys():
        if key in QOS_DYNAMIC_KEYS:
            qos[QOS_DYNAMIC_KEY_MAP[key]] = _get_qos_dynamic_value(
                key, specs['specs'][key], size, specs['specs'])

    return qos


DICT = '_dict'
CONF = '_conf'
OPTS = '_opts'


class Config(object):

    def __init__(self, conf, opts):
        super().__setattr__(CONF, conf)
        super().__setattr__(DICT, dict())
        super().__setattr__(OPTS, opts)

    def __getitem__(self, name):
        return (super().__getattribute__(DICT)[name]
                if name in super().__getattribute__(DICT)
                else super().__getattribute__(CONF).safe_get(name))

    def __getattr__(self, name):
        return (super().__getattribute__(DICT)[name]
                if name in super().__getattribute__(DICT)
                else getattr(super().__getattribute__(CONF), name))

    def __setitem__(self, key, value):
        super().__getattribute__(DICT)[key] = value

    def __setattr__(self, key, value):
        self.__setitem__(key, value)

    def safe_get(self, name):
        return (super().__getattribute__(DICT)[name]
                if name in super().__getattribute__(DICT)
                else super().__getattribute__(CONF).safe_get(name))

    def update(self, name, val):
        opt = super().__getattribute__(OPTS)[name]
        if val is not None:
            if isinstance(opt.type(val), list):
                val = val.replace(';', ',')
            super().__getattribute__(DICT)[name] = opt.type(val)
        else:
            super().__getattribute__(DICT)[name] = opt.default


class HostConnectorSearcher(object):
    '''Searcher for host connections.'''

    def __init__(self, queryFunc: typing.Callable):
        # The query function has a signature like this:
        #    def Query(port: str, group: int | str | None) ->
        #       list[str] | tuple[tuple[int, Any], list[str]] |
        #       list[tuple[int, Any]]

        # Query functionality if group is:
        #        int: do a lookup for the given group by number.
        #             return list of WWNs/targets found
        #        str: do a lookup for the given group by name.
        #             return tuple of group #/metadata tuple, and list of
        #             WWNs/targets found (tuple[tuple[int, Any], list[str]]).
        #             If the host group is not found, this should return None.
        #             and an empty list.
        #        other: do a lookup for all groups on the port
        #            return list of tuples of groups/metadata groups found
        #                   (tuple[int, Any])

        self._queryFunc = queryFunc

    def find(self, port: str, targetOrWwns: list[str],
             groupNameHints: list[str]) -> tuple[int, typing.Any] | None:
        '''Find the group for the given target or WWN.'''

        # This method finds the group for the given target or
        # WWN in the cache. If it does not exist in the cache,
        # it will do a search on the storage using the queryFunc.
        # When performing the search, it will first use groupNameHints
        # to query the host groups named there.'''

        # If we've been given groupNameHints, we'll look for those
        # groups first.
        groupAndMeta = None
        if groupNameHints:
            for groupName in groupNameHints:
                if groupAndMeta is not None:  # If we found our group, bail out
                    break
                res = self._queryGroupByName(port, groupName)
                if res is None:
                    continue
                groupAndMetaTemp, targets = res
                for target in targets:
                    # Compare target and set if found.
                    if target in targetOrWwns:
                        groupAndMeta = groupAndMetaTemp
                    # If we found our group, bail out.
                    if groupAndMeta is not None:
                        break

        # If we still don't have a group, we'll use our queryFunc
        # to find it (if possible).
        if groupAndMeta is None:
            # Query the group list.
            searchGroupsAndMeta = self._queryGroupsOnPort(port)

            # For each group, query the WWN(s) until we find what we're
            # looking for. Cache all WWNs/groups found.
            for searchGroupAndMeta in searchGroupsAndMeta:
                groupTemp, metaTemp = searchGroupAndMeta

                targets = self._queryGroup(port, groupTemp)

                for target in targets:
                    if target in targetOrWwns:
                        groupAndMeta = searchGroupAndMeta
                    # If we found our group, bail out.
                    if groupAndMeta is not None:
                        break

                # If we found our group, bail out.
                if groupAndMeta is not None:
                    break

        return groupAndMeta

    def _queryGroupByName(self, port: str,
                          group: str) -> tuple[tuple[int, typing.Any],
                                               list[str]] | None:
        return self._queryFunc(port, group)

    def _queryGroup(self, port: str, group: int) -> list[str]:
        return self._queryFunc(port, group)

    def _queryGroupsOnPort(self, port: str) -> list[tuple[int, typing.Any]]:
        return self._queryFunc(port, None)

    def on_reset(self):
        '''Reset any caching.'''

        # This notifies that the system has changed in some way and
        # is requesting a reset of any caches, etc.
        pass

    def on_reset_group(self, port: str, group: int):
        '''Reset any cache for the given group.'''

        # This notifies that the system has changed in some way in
        # relation to the given group information and is
        # requesting a reset of caches around this relationship.
        pass


class ConnectorSearcherCache(object):
    '''Cache for the host connector searcher.'''

    def __init__(self):

        # This represents the cache of ports & targets/WWNs to group numbers.
        # key: str [_generate_target_key(port, target/WWN)]
        # value: tuple(int, typing.Any) [group #, meta-data]
        self._target_cache = dict()
        # This represents the cache of port/group number to group information.
        # key: str [_generate_group_key(port, group)]
        # value: tuple(str | None, list[str]) [name, target/wwn list]
        self._group_cache = dict()
        # This represents the cache of port/group name to group number.
        # key: str [_generate_group_name_key(port, groupName)
        # value: int [group #]
        self._group_name_cache = dict()
        self._separator = '\t'

    def _generate_target_key(self, port: str, targetOrWwn: str) -> str:
        return (port + self._separator + targetOrWwn)

    def _generate_group_key(self, port: str, group: int) -> str:
        return (port + self._separator + str(group))

    def _generate_group_name_key(self, port: str, groupName: str) -> str:
        # Triple separators between port and group to avoid collisions.
        return (port + self._separator + groupName)

    def lookup(self, port: str,
               targetOrWwn: str) -> tuple[int, typing.Any] | None:
        '''Find the group/meta information for the given target/WWN.'''

        key = self._generate_target_key(port, targetOrWwn)
        ret = self._target_cache.get(key, None)
        if ret:
            LOG.debug('Found group (and meta) %(group)s for target/WWN '
                      '%(target)s on port %(port)s in cache.',
                      {'group': ret, 'target': targetOrWwn, 'port': port})
        return ret

    def is_group_cached(self, port: str, group: int) -> bool:
        '''Determine if the given group is in our cache.'''

        key = self._generate_group_key(port, group)
        return self._group_cache.get(key, None) is not None

    def is_group_name_cached(self, port: str, groupName: str) -> bool:
        '''Determine if the given group name is in our cache.'''

        key = self._generate_group_name_key(port, groupName)
        return self._group_name_cache.get(key, None) is not None

    def cache(self, port: str, groupAndMeta: tuple[int, typing.Any],
              groupName: str | None, targetsOrWwns: list[str] | None):
        '''Cache the given group and its associations.'''

        targetList = list()

        # Extract our group number.
        group, _ = groupAndMeta
        LOG.debug("Caching information for group %(group)s.",
                  {'group': group})

        # 1. Cache our targets/WWNs with the given group/meta data.
        # 2. Also build our target list for our group cache. We won't use
        #    the given list directly to avoid a situation where it gets
        #    modified elsewhere.
        if targetsOrWwns:
            for targetOrWwn in targetsOrWwns:
                key = self._generate_target_key(port, targetOrWwn)
                LOG.debug("Caching target to group %(targetKey)s:%(group)s.",
                          {'targetKey': key, 'group': group})
                self._target_cache[key] = groupAndMeta
                targetList.append(targetOrWwn)

        # Cache our group information.
        key = self._generate_group_key(port, group)
        self._group_cache[key] = (groupName, targetList)

        # Cache our group name information if we have any.
        if groupName:
            key = self._generate_group_name_key(port, groupName)
            LOG.debug("Caching group name to group%(groupNameKey)s:%(group)s.",
                      {'groupNameKey': key, 'group': group})
            self._group_name_cache[key] = group

    def clear(self):

        # Clear the entire cache.
        self._target_cache.clear()
        self._group_cache.clear()
        self._group_name_cache.clear()

    def clear_group(self, port: str, group: int):

        # Clear the given group from the cache.
        # This will clear the group in its entirety from all 3 caches.

        groupKey = self._generate_group_key(port, group)
        groupInfo = self._group_cache.get(groupKey, None)
        if groupInfo:
            name, targets = groupInfo
            if name:
                groupNameKey = self._generate_group_name_key(port, name)
                del self._group_name_cache[groupNameKey]
            for target in targets:
                targetKey = self._generate_target_key(port, target)
                del self._target_cache[targetKey]
            del self._group_cache[groupKey]


class CachingHostConnectorSearcher(HostConnectorSearcher):
    '''Caching version of the host connector searcher.'''

    def __init__(self, storage_id, queryFunc: typing.Callable):
        super(CachingHostConnectorSearcher, self).__init__(queryFunc)
        self._storage_id = storage_id
        self._connector_cache = ConnectorSearcherCache()
        self._cache_lock = threading.Lock()

    # Only allow 1 search at a time per storage/port.
    # This is because it's very expensive, and when a search is ongoing
    # the next caller may have already had their data cached.
    # So the next caller can come in and check the cache again when they
    # have access to the lock.
    # Note that this will also prevent cross-node searches simultaneously.
    # We may want to change that in the future, but for the time being it
    # will prevent the storage API from being overwhelmed on big searches.
    @coordination.synchronized(
        'target-search-{self._storage_id}-{port}')
    def _locked_search(self, port: str, targetOrWwns: list[str],
                       groupNameHints: list[str])\
            -> tuple[int, typing.Any] | None:
        '''Perform the search with a lock.'''

        # Once we have our search lock we'll do a lookup
        # in the cache again as another caller may have
        # been doing a simultaneous search if we waited.
        groupAndMeta = None
        for targetOrWwn in targetOrWwns:
            groupAndMeta = self._lookup(port, targetOrWwn)
            if groupAndMeta is not None:
                break

        if groupAndMeta is None:
            LOG.debug('Group not found in cache for port %(port)s '
                      'and target/WWNs %(targets)s. '
                      'Performing search.',
                      {'port': port, 'targets': targetOrWwns})

            # If we've been given groupNameHints, we'll look for those
            # groups first.
            if groupNameHints:
                for groupName in groupNameHints:
                    # If we already searched our group, skip it.
                    if self._is_group_name_cached(port, groupName):
                        LOG.debug('Skipping cached group %(group)s '
                                  'on port %(port)s.',
                                  {'group': groupName,
                                   'port': port})
                        continue

                    res = self._queryGroupByName(port, groupName)
                    if res is None:
                        continue
                    searchGroupAndMeta, targets = res

                    # Only cache the group name if the group actually exists.
                    # Cache searches will eventually cache everything
                    # necessary.
                    groupAndMeta = self._find_and_cache(port,
                                                        searchGroupAndMeta,
                                                        targetOrWwns,
                                                        targets,
                                                        groupName)

            # If we still don't have a group, we'll use our queryFunc
            # to find it (if possible).
            if groupAndMeta is None:
                # Query the group list.
                searchGroupsAndMeta = self._queryGroupsOnPort(port)

                # For each group, query the WWN(s) until we find what
                # we're looking for. Cache all WWNs/groups found.
                for searchGroupAndMeta in searchGroupsAndMeta:
                    searchGroup, searchMeta = searchGroupAndMeta
                    if self._is_group_cached(port, searchGroup):
                        LOG.debug('Skipping cached group %(group)s '
                                  'on port %(port)s.',
                                  {'group': searchGroup,
                                   'port': port})
                        continue

                    targets = self._queryGroup(port, searchGroup)
                    groupAndMeta = self._find_and_cache(port,
                                                        searchGroupAndMeta,
                                                        targetOrWwns, targets,
                                                        None)

                    # If we found our group then stop the search.
                    if groupAndMeta is not None:
                        LOG.debug('Group/meta %(group)s found for port '
                                  '%(port)s and target/WWN '
                                  '%(targets)s.',
                                  {'group': groupAndMeta, 'port': port,
                                   'targets': targetOrWwns})
                        break

        return groupAndMeta

    def find(self, port: str, targetOrWwns: list[str],
             groupNameHints: list[str]) -> tuple[int, typing.Any] | None:
        '''Find the group for the given target or WWN.'''

        # This method finds the group for the given target or
        # WWN in the cache. If it does not exist in the cache,
        # it will do a search on the storage using the queryFunc.
        # When performing the search, it will first use groupNameHints
        # to query the host groups named there.'''
        groupAndMeta = None
        for targetOrWwn in targetOrWwns:
            groupAndMeta = self._lookup(port, targetOrWwn)
            if groupAndMeta is not None:
                break
        if groupAndMeta is None:
            groupAndMeta = self._locked_search(port, targetOrWwns,
                                               groupNameHints)
        return groupAndMeta

    def _find_and_cache(self, port: str, groupAndMeta: tuple[int, typing.Any],
                        searchTargets: list[str], targets: list[str],
                        groupName: str | None)\
            -> tuple[int, typing.Any] | None:

        with self._cache_lock:
            self._connector_cache.cache(port, groupAndMeta, groupName, targets)

        foundGroup = None
        if targets:
            for searchTarget in searchTargets:
                if searchTarget in targets:
                    foundGroup = groupAndMeta
                    break

        return foundGroup

    def _lookup(self, port: str,
                targetOrWwn: str) -> tuple[int, typing.Any] | None:
        with self._cache_lock:
            return self._connector_cache.lookup(port, targetOrWwn)

    def _is_group_cached(self, port: str, group: int) -> bool:
        with self._cache_lock:
            return self._connector_cache.is_group_cached(port, group)

    def _is_group_name_cached(self, port: str, groupName: str) -> bool:
        with self._cache_lock:
            return self._connector_cache.is_group_name_cached(port, groupName)

    def on_reset(self):
        '''Reset the entire cache.'''

        LOG.debug("Resetting entire cache.")

        with self._cache_lock:
            self._connector_cache.clear()

    def on_reset_group(self, port: str, group: int):
        '''Reset the cache for the given group.'''

        LOG.debug('Resetting cache for group: %(port)s-%(group)s.',
                  {'port': port, 'group': group})

        with self._cache_lock:
            self._connector_cache.clear_group(port, group)
