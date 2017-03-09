# Copyright (C) 2016, Hitachi, Ltd.
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
"""Utility module for Hitachi VSP Driver."""

import functools
import inspect
import logging as base_logging
import os
import re

import enum
from oslo_concurrency import processutils as putils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import units
import six

from cinder import exception
from cinder import utils as cinder_utils


_DRIVER_DIR = 'cinder.volume.drivers.hitachi'

_DRIVERS = {
    'HORCM': {
        'FC': 'vsp_horcm_fc.VSPHORCMFC',
        'iSCSI': 'vsp_horcm_iscsi.VSPHORCMISCSI',
    },
}

DRIVER_PREFIX = 'VSP'
TARGET_PREFIX = 'HBSD-'
TARGET_IQN_SUFFIX = '.hbsd-target'
GIGABYTE_PER_BLOCK_SIZE = units.Gi / 512

MAX_PROCESS_WAITTIME = 24 * 60 * 60
DEFAULT_PROCESS_WAITTIME = 15 * 60

NORMAL_LDEV_TYPE = 'Normal'
NVOL_LDEV_TYPE = 'DP-VOL'

FULL = 'Full copy'
THIN = 'Thin copy'

INFO_SUFFIX = 'I'
WARNING_SUFFIX = 'W'
ERROR_SUFFIX = 'E'

PORT_ID_LENGTH = 5


@enum.unique
class VSPMsg(enum.Enum):
    """messages for Hitachi VSP Driver."""

    METHOD_START = {
        'msg_id': 0,
        'loglevel': base_logging.INFO,
        'msg': '%(method)s starts. (config_group: %(config_group)s)',
        'suffix': INFO_SUFFIX
    }
    OUTPUT_PARAMETER_VALUES = {
        'msg_id': 1,
        'loglevel': base_logging.INFO,
        'msg': 'The parameter of the storage backend. (config_group: '
               '%(config_group)s)',
        'suffix': INFO_SUFFIX
    }
    METHOD_END = {
        'msg_id': 2,
        'loglevel': base_logging.INFO,
        'msg': '%(method)s ended. (config_group: %(config_group)s)',
        'suffix': INFO_SUFFIX
    }
    DRIVER_READY_FOR_USE = {
        'msg_id': 3,
        'loglevel': base_logging.INFO,
        'msg': 'The storage backend can be used. (config_group: '
               '%(config_group)s)',
        'suffix': INFO_SUFFIX
    }
    DRIVER_INITIALIZATION_START = {
        'msg_id': 4,
        'loglevel': base_logging.INFO,
        'msg': 'Initialization of %(driver)s %(version)s started.',
        'suffix': INFO_SUFFIX
    }
    SET_CONFIG_VALUE = {
        'msg_id': 5,
        'loglevel': base_logging.INFO,
        'msg': 'Set %(object)s to %(value)s.',
        'suffix': INFO_SUFFIX
    }
    OBJECT_CREATED = {
        'msg_id': 6,
        'loglevel': base_logging.INFO,
        'msg': 'Created %(object)s. (%(details)s)',
        'suffix': INFO_SUFFIX
    }
    INVALID_LDEV_FOR_UNMAPPING = {
        'msg_id': 302,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to specify a logical device for the volume '
               '%(volume_id)s to be unmapped.',
        'suffix': WARNING_SUFFIX
    }
    INVALID_LDEV_FOR_DELETION = {
        'msg_id': 304,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to specify a logical device to be deleted. '
               '(method: %(method)s, id: %(id)s)',
        'suffix': WARNING_SUFFIX
    }
    DELETE_TARGET_FAILED = {
        'msg_id': 306,
        'loglevel': base_logging.WARNING,
        'msg': 'A host group or an iSCSI target could not be deleted. '
               '(port: %(port)s, gid: %(id)s)',
        'suffix': WARNING_SUFFIX
    }
    CREATE_HOST_GROUP_FAILED = {
        'msg_id': 308,
        'loglevel': base_logging.WARNING,
        'msg': 'A host group could not be added. (port: %(port)s)',
        'suffix': WARNING_SUFFIX
    }
    CREATE_ISCSI_TARGET_FAILED = {
        'msg_id': 309,
        'loglevel': base_logging.WARNING,
        'msg': 'An iSCSI target could not be added. (port: %(port)s)',
        'suffix': WARNING_SUFFIX
    }
    UNMAP_LDEV_FAILED = {
        'msg_id': 310,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to unmap a logical device. (LDEV: %(ldev)s)',
        'suffix': WARNING_SUFFIX
    }
    DELETE_LDEV_FAILED = {
        'msg_id': 313,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to delete a logical device. (LDEV: %(ldev)s)',
        'suffix': WARNING_SUFFIX
    }
    MAP_LDEV_FAILED = {
        'msg_id': 314,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to map a logical device. (LDEV: %(ldev)s, port: '
               '%(port)s, id: %(id)s, lun: %(lun)s)',
        'suffix': WARNING_SUFFIX
    }
    DISCARD_ZERO_PAGE_FAILED = {
        'msg_id': 315,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to perform a zero-page reclamation. (LDEV: '
               '%(ldev)s)',
        'suffix': WARNING_SUFFIX
    }
    ADD_HBA_WWN_FAILED = {
        'msg_id': 317,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to assign the WWN. (port: %(port)s, gid: %(gid)s, '
               'wwn: %(wwn)s)',
        'suffix': WARNING_SUFFIX
    }
    LDEV_NOT_EXIST = {
        'msg_id': 319,
        'loglevel': base_logging.WARNING,
        'msg': 'The logical device does not exist in the storage system. '
               '(LDEV: %(ldev)s)',
        'suffix': WARNING_SUFFIX
    }
    HORCM_START_FAILED = {
        'msg_id': 320,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to start HORCM. (inst: %(inst)s)',
        'suffix': WARNING_SUFFIX
    }
    HORCM_RESTART_FOR_SI_FAILED = {
        'msg_id': 322,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to reload the configuration of full copy pair. '
               '(inst: %(inst)s)',
        'suffix': WARNING_SUFFIX
    }
    HORCM_LOGIN_FAILED = {
        'msg_id': 323,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to perform user authentication of HORCM. '
               '(user: %(user)s)',
        'suffix': WARNING_SUFFIX
    }
    DELETE_SI_PAIR_FAILED = {
        'msg_id': 324,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to delete full copy pair. (P-VOL: %(pvol)s, S-VOL: '
               '%(svol)s)',
        'suffix': WARNING_SUFFIX
    }
    DELETE_TI_PAIR_FAILED = {
        'msg_id': 325,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to delete thin copy pair. (P-VOL: %(pvol)s, S-VOL: '
               '%(svol)s)',
        'suffix': WARNING_SUFFIX
    }
    WAIT_SI_PAIR_STATUS_FAILED = {
        'msg_id': 326,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to change the status of full copy pair. (P-VOL: '
               '%(pvol)s, S-VOL: %(svol)s)',
        'suffix': WARNING_SUFFIX
    }
    DELETE_DEVICE_GRP_FAILED = {
        'msg_id': 327,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to delete the configuration of full copy pair. '
               '(P-VOL: %(pvol)s, S-VOL: %(svol)s)',
        'suffix': WARNING_SUFFIX
    }
    DISCONNECT_VOLUME_FAILED = {
        'msg_id': 329,
        'loglevel': base_logging.WARNING,
        'msg': 'Failed to detach the logical device. (LDEV: %(ldev)s, '
               'reason: %(reason)s)',
        'suffix': WARNING_SUFFIX
    }
    STORAGE_COMMAND_FAILED = {
        'msg_id': 600,
        'loglevel': base_logging.ERROR,
        'msg': 'The command %(cmd)s failed. (ret: %(ret)s, stdout: '
               '%(out)s, stderr: %(err)s)',
        'suffix': ERROR_SUFFIX
    }
    INVALID_PARAMETER = {
        'msg_id': 601,
        'loglevel': base_logging.ERROR,
        'msg': 'A parameter is invalid. (%(param)s)',
        'suffix': ERROR_SUFFIX
    }
    INVALID_PARAMETER_VALUE = {
        'msg_id': 602,
        'loglevel': base_logging.ERROR,
        'msg': 'A parameter value is invalid. (%(meta)s)',
        'suffix': ERROR_SUFFIX
    }
    HORCM_SHUTDOWN_FAILED = {
        'msg_id': 608,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to shutdown HORCM. (inst: %(inst)s)',
        'suffix': ERROR_SUFFIX
    }
    HORCM_RESTART_FAILED = {
        'msg_id': 609,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to restart HORCM. (inst: %(inst)s)',
        'suffix': ERROR_SUFFIX
    }
    SI_PAIR_STATUS_WAIT_TIMEOUT = {
        'msg_id': 610,
        'loglevel': base_logging.ERROR,
        'msg': 'The status change of full copy pair could not be '
               'completed. (S-VOL: %(svol)s)',
        'suffix': ERROR_SUFFIX
    }
    TI_PAIR_STATUS_WAIT_TIMEOUT = {
        'msg_id': 611,
        'loglevel': base_logging.ERROR,
        'msg': 'The status change of thin copy pair could not be '
               'completed. (S-VOL: %(svol)s)',
        'suffix': ERROR_SUFFIX
    }
    INVALID_LDEV_STATUS_FOR_COPY = {
        'msg_id': 612,
        'loglevel': base_logging.ERROR,
        'msg': 'The source logical device to be replicated does not exist '
               'in the storage system. (LDEV: %(ldev)s)',
        'suffix': ERROR_SUFFIX
    }
    INVALID_LDEV_FOR_EXTENSION = {
        'msg_id': 613,
        'loglevel': base_logging.ERROR,
        'msg': 'The volume %(volume_id)s to be extended was not found.',
        'suffix': ERROR_SUFFIX
    }
    NO_HBA_WWN_ADDED_TO_HOST_GRP = {
        'msg_id': 614,
        'loglevel': base_logging.ERROR,
        'msg': 'No WWN is assigned. (port: %(port)s, gid: %(gid)s)',
        'suffix': ERROR_SUFFIX
    }
    NO_AVAILABLE_MIRROR_UNIT = {
        'msg_id': 615,
        'loglevel': base_logging.ERROR,
        'msg': 'A pair could not be created. The maximum number of pair '
               'is exceeded. (copy method: %(copy_method)s, P-VOL: '
               '%(pvol)s)',
        'suffix': ERROR_SUFFIX
    }
    UNABLE_TO_DELETE_PAIR = {
        'msg_id': 616,
        'loglevel': base_logging.ERROR,
        'msg': 'A pair cannot be deleted. (P-VOL: %(pvol)s, S-VOL: '
               '%(svol)s)',
        'suffix': ERROR_SUFFIX
    }
    INVALID_VOLUME_SIZE_FOR_COPY = {
        'msg_id': 617,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to create a volume from a %(type)s. The size of '
               'the new volume must be equal to or greater than the size '
               'of the original %(type)s. (new volume: %(volume_id)s)',
        'suffix': ERROR_SUFFIX
    }
    INVALID_VOLUME_TYPE_FOR_EXTEND = {
        'msg_id': 618,
        'loglevel': base_logging.ERROR,
        'msg': 'The volume %(volume_id)s could not be extended. The '
               'volume type must be Normal.',
        'suffix': ERROR_SUFFIX
    }
    INVALID_LDEV_FOR_CONNECTION = {
        'msg_id': 619,
        'loglevel': base_logging.ERROR,
        'msg': 'The volume %(volume_id)s to be mapped was not found.',
        'suffix': ERROR_SUFFIX
    }
    POOL_INFO_RETRIEVAL_FAILED = {
        'msg_id': 620,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to provide information about a pool. (pool: '
               '%(pool)s)',
        'suffix': ERROR_SUFFIX
    }
    INVALID_VOLUME_SIZE_FOR_TI = {
        'msg_id': 621,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to create a volume from a %(type)s. The size of '
               'the new volume must be equal to the size of the original '
               '%(type)s when the new volume is created by '
               '%(copy_method)s. (new volume: %(volume_id)s)',
        'suffix': ERROR_SUFFIX
    }
    INVALID_LDEV_FOR_VOLUME_COPY = {
        'msg_id': 624,
        'loglevel': base_logging.ERROR,
        'msg': 'The %(type)s %(id)s source to be replicated was not '
               'found.',
        'suffix': ERROR_SUFFIX
    }
    CREATE_HORCM_CONF_FILE_FAILED = {
        'msg_id': 632,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to open a file. (file: %(file)s, ret: %(ret)s, '
               'stderr: %(err)s)',
        'suffix': ERROR_SUFFIX
    }
    CONNECT_VOLUME_FAILED = {
        'msg_id': 634,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to attach the logical device. (LDEV: %(ldev)s, '
               'reason: %(reason)s)',
        'suffix': ERROR_SUFFIX
    }
    CREATE_LDEV_FAILED = {
        'msg_id': 636,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to add the logical device.',
        'suffix': ERROR_SUFFIX
    }
    ADD_PAIR_TARGET_FAILED = {
        'msg_id': 638,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to add the pair target.',
        'suffix': ERROR_SUFFIX
    }
    NO_MAPPING_FOR_LDEV = {
        'msg_id': 639,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to map a logical device to any pair targets. '
               '(LDEV: %(ldev)s)',
        'suffix': ERROR_SUFFIX
    }
    POOL_NOT_FOUND = {
        'msg_id': 640,
        'loglevel': base_logging.ERROR,
        'msg': 'A pool could not be found. (pool: %(pool)s)',
        'suffix': ERROR_SUFFIX
    }
    NO_AVAILABLE_RESOURCE = {
        'msg_id': 648,
        'loglevel': base_logging.ERROR,
        'msg': 'There are no resources available for use. (resource: '
               '%(resource)s)',
        'suffix': ERROR_SUFFIX
    }
    NO_CONNECTED_TARGET = {
        'msg_id': 649,
        'loglevel': base_logging.ERROR,
        'msg': 'The host group or iSCSI target was not found.',
        'suffix': ERROR_SUFFIX
    }
    RESOURCE_NOT_FOUND = {
        'msg_id': 650,
        'loglevel': base_logging.ERROR,
        'msg': 'The resource %(resource)s was not found.',
        'suffix': ERROR_SUFFIX
    }
    LDEV_DELETION_WAIT_TIMEOUT = {
        'msg_id': 652,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to delete a logical device. (LDEV: %(ldev)s)',
        'suffix': ERROR_SUFFIX
    }
    LDEV_CREATION_WAIT_TIMEOUT = {
        'msg_id': 653,
        'loglevel': base_logging.ERROR,
        'msg': 'The creation of a logical device could not be completed. '
               '(LDEV: %(ldev)s)',
        'suffix': ERROR_SUFFIX
    }
    INVALID_LDEV_ATTR_FOR_MANAGE = {
        'msg_id': 702,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to manage the specified LDEV (%(ldev)s). The LDEV '
               'must be an unpaired %(ldevtype)s.',
        'suffix': ERROR_SUFFIX
    }
    INVALID_LDEV_SIZE_FOR_MANAGE = {
        'msg_id': 703,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to manage the specified LDEV (%(ldev)s). The LDEV '
               'size must be expressed in gigabytes.',
        'suffix': ERROR_SUFFIX
    }
    INVALID_LDEV_PORT_FOR_MANAGE = {
        'msg_id': 704,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to manage the specified LDEV (%(ldev)s). The LDEV '
               'must not be mapped.',
        'suffix': ERROR_SUFFIX
    }
    INVALID_LDEV_TYPE_FOR_UNMANAGE = {
        'msg_id': 706,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to unmanage the volume %(volume_id)s. The volume '
               'type must be %(volume_type)s.',
        'suffix': ERROR_SUFFIX
    }
    INVALID_LDEV_FOR_MANAGE = {
        'msg_id': 707,
        'loglevel': base_logging.ERROR,
        'msg': 'No valid value is specified for "source-id". A valid LDEV '
               'number must be specified in "source-id" to manage the '
               'volume.',
        'suffix': ERROR_SUFFIX
    }
    VOLUME_COPY_FAILED = {
        'msg_id': 722,
        'loglevel': base_logging.ERROR,
        'msg': 'Failed to copy a volume. (copy method: %(copy_method)s, '
               'P-VOL: %(pvol)s, S-VOL: %(svol)s)',
        'suffix': ERROR_SUFFIX
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
MSG = VSPMsg


def output_start_end_log(func):
    """Output the log of the start and the end of the method."""
    @functools.wraps(func)
    def wrap(self, *args, **kwargs):
        """Wrap the method to add logging function."""
        def _output_start_end_log(*_args, **_kwargs):
            """Output the log of the start and the end of the method."""
            output_log(MSG.METHOD_START,
                       method=func.__name__,
                       config_group=self.configuration.config_group)
            ret = func(*_args, **_kwargs)
            output_log(MSG.METHOD_END,
                       method=func.__name__,
                       config_group=self.configuration.config_group)
            return ret
        return _output_start_end_log(self, *args, **kwargs)
    return wrap


def get_ldev(obj):
    """Get the LDEV number from the given object and return it as integer."""
    if not obj:
        return None
    ldev = obj.get('provider_location')
    if not ldev or not ldev.isdigit():
        return None
    return int(ldev)


def check_timeout(start_time, timeout):
    """Return True if the specified time has passed, False otherwise."""
    return timeutils.is_older_than(start_time, timeout)


def mask_password(cmd):
    """Return a string in which the password is masked."""
    if len(cmd) > 3 and cmd[0] == 'raidcom' and cmd[1] == '-login':
        tmp = list(cmd)
        tmp[3] = strutils.mask_dict_password({'password': ''}).get('password')
    else:
        tmp = cmd
    return ' '.join([six.text_type(c) for c in tmp])


def execute(*cmd, **kwargs):
    """Run the specified command and return its results."""
    process_input = kwargs.pop('process_input', None)
    run_as_root = kwargs.pop('run_as_root', True)
    ret = 0
    try:
        if len(cmd) > 3 and cmd[0] == 'raidcom' and cmd[1] == '-login':
            stdout, stderr = cinder_utils.execute(
                *cmd, process_input=process_input, run_as_root=run_as_root,
                loglevel=base_logging.NOTSET)[:2]
        else:
            stdout, stderr = cinder_utils.execute(
                *cmd, process_input=process_input, run_as_root=run_as_root)[:2]
    except putils.ProcessExecutionError as ex:
        ret = ex.exit_code
        stdout = ex.stdout
        stderr = ex.stderr
        LOG.debug('cmd: %s', mask_password(cmd))
        LOG.debug('from: %s', inspect.stack()[2])
        LOG.debug('ret: %s', ret)
        LOG.debug('stdout: %s', ' '.join(stdout.splitlines()))
        LOG.debug('stderr: %s', ' '.join(stderr.splitlines()))
    return ret, stdout, stderr


def import_object(conf, driver_info, db):
    """Import a class and return an instance of it."""
    os.environ['LANG'] = 'C'
    cli = _DRIVERS.get('HORCM')
    return importutils.import_object(
        '.'.join([_DRIVER_DIR, cli[driver_info['proto']]]),
        conf, driver_info, db)


def check_ignore_error(ignore_error, stderr):
    """Return True if ignore_error is in stderr, False otherwise."""
    if not ignore_error or not stderr:
        return False
    if not isinstance(ignore_error, six.string_types):
        ignore_error = '|'.join(ignore_error)

    if re.search(ignore_error, stderr):
        return True
    return False


def check_opts(conf, opts):
    """Check if the specified configuration is valid."""
    names = []
    for opt in opts:
        names.append(opt.name)
    check_opt_value(conf, names)


def check_opt_value(conf, names):
    """Check if the parameter names and values are valid."""
    for name in names:
        try:
            getattr(conf, name)
        except (cfg.NoSuchOptError, cfg.ConfigFileValueError):
            with excutils.save_and_reraise_exception():
                output_log(MSG.INVALID_PARAMETER, param=name)


def output_storage_cli_info(name, version):
    """Output storage CLI info to the log file."""
    LOG.info('\t%(name)-35s%(version)s',
             {'name': name + ' version: ', 'version': version})


def output_opt_info(conf, names):
    """Output parameter names and values to the log file."""
    for name in names:
        LOG.info('\t%(name)-35s%(attr)s',
                 {'name': name + ': ', 'attr': getattr(conf, name)})


def output_opts(conf, opts):
    """Output parameter names and values to the log file."""
    names = [opt.name for opt in opts if not opt.secret]
    output_opt_info(conf, names)


def require_target_existed(targets):
    """Check if the target list includes one or more members."""
    if not targets['list']:
        msg = output_log(MSG.NO_CONNECTED_TARGET)
        raise exception.VSPError(msg)


def get_volume_metadata(volume):
    """Return a dictionary of the metadata of the specified volume."""
    volume_metadata = volume.get('volume_metadata', {})
    return {item['key']: item['value'] for item in volume_metadata}


def update_conn_info(conn_info, connector, lookup_service):
    """Set wwn mapping list to the connection info."""
    init_targ_map = build_initiator_target_map(
        connector, conn_info['data']['target_wwn'], lookup_service)
    if init_targ_map:
        conn_info['data']['initiator_target_map'] = init_targ_map


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
