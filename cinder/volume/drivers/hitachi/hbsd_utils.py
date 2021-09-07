# Copyright (C) 2020, Hitachi, Ltd.
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
import logging as base_logging
import os

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import timeutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _

_DRIVER_DIR = 'cinder.volume.drivers.hitachi'

_DRIVERS = {
    'REST': {
        'FC': 'hbsd_rest_fc.HBSDRESTFC',
        'iSCSI': 'hbsd_rest_iscsi.HBSDRESTISCSI',
    },
}

DRIVER_PREFIX = 'HBSD'
TARGET_PREFIX = 'HBSD-'
TARGET_IQN_SUFFIX = '.hbsd-target'
GIGABYTE_PER_BLOCK_SIZE = units.Gi / 512

MAX_PROCESS_WAITTIME = 24 * 60 * 60
DEFAULT_PROCESS_WAITTIME = 15 * 60

NORMAL_LDEV_TYPE = 'Normal'
NVOL_LDEV_TYPE = 'DP-VOL'

INFO_SUFFIX = 'I'
WARNING_SUFFIX = 'W'
ERROR_SUFFIX = 'E'

PORT_ID_LENGTH = 5


class HBSDError(exception.VolumeDriverException):
    message = _("HBSD error occurred. %(message)s")


class HBSDBusy(HBSDError):
    message = _("Device or resource is busy.")


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
    INVALID_PORT = {
        'msg_id': 339,
        'loglevel': base_logging.WARNING,
        'msg': 'Port %(port)s will not be used because its settings are '
               'invalid. (%(additional_info)s)',
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
    VOLUME_COPY_FAILED = {
        'msg_id': 725,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to copy a volume. (copy method: %(copy_method)s, '
               'P-VOL: %(pvol)s, S-VOL: %(svol)s)',
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

    def __init__(self, error_info):
        """Initialize Enum attributes."""
        self.msg_id = error_info['msg_id']
        self.level = error_info['loglevel']
        self.msg = error_info['msg']
        self.suffix = error_info['suffix']

    def output_log(self, **kwargs):
        """Output the message to the log file and return the message."""
        msg = self.msg % kwargs
        LOG.log(self.level, "MSGID%(msg_id)04d-%(msg_suffix)s: %(msg)s",
                {'msg_id': self.msg_id, 'msg_suffix': self.suffix, 'msg': msg})
        return msg


def output_log(msg_enum, **kwargs):
    """Output the specified message to the log file and return the message."""
    return msg_enum.output_log(**kwargs)


LOG = logging.getLogger(__name__)
MSG = HBSDMsg


def get_ldev(obj):
    """Get the LDEV number from the given object and return it as integer."""
    if not obj:
        return None
    ldev = obj.get('provider_location')
    if not ldev or not ldev.isdigit():
        return None
    return int(ldev)


def timed_out(start_time, timeout):
    """Check if the specified time has passed."""
    return timeutils.is_older_than(start_time, timeout)


def import_object(conf, driver_info, db):
    """Import a class and return an instance of it."""
    os.environ['LANG'] = 'C'
    cli = _DRIVERS.get('REST')
    return importutils.import_object(
        '%(dir)s.%(proto)s' % {
            'dir': _DRIVER_DIR,
            'proto': cli[driver_info['proto']],
        },
        conf, driver_info, db)


def check_opt_value(conf, names):
    """Check if the parameter names and values are valid."""
    for name in names:
        try:
            getattr(conf, name)
        except (cfg.NoSuchOptError, cfg.ConfigFileValueError):
            with excutils.save_and_reraise_exception():
                output_log(MSG.INVALID_PARAMETER, param=name)


def check_opts(conf, opts):
    """Check if the specified configuration is valid."""
    names = []
    for opt in opts:
        if opt.required and not conf.safe_get(opt.name):
            msg = output_log(MSG.INVALID_PARAMETER, param=opt.name)
            raise HBSDError(msg)
        names.append(opt.name)
    check_opt_value(conf, names)


def require_target_existed(targets):
    """Check if the target list includes one or more members."""
    if not targets['list']:
        msg = output_log(MSG.NO_CONNECTED_TARGET)
        raise HBSDError(msg)


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
