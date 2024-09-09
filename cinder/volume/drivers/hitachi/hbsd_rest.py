# Copyright (C) 2020, 2024, Hitachi, Ltd.
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
"""REST interface module for Hitachi HBSD Driver."""

from collections import defaultdict
import re

from oslo_config import cfg
from oslo_config import types
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import timeutils
from oslo_utils import units

from cinder import exception
from cinder.objects import fields
from cinder.objects import SnapshotList
from cinder.volume import configuration
from cinder.volume.drivers.hitachi import hbsd_common as common
from cinder.volume.drivers.hitachi import hbsd_rest_api as rest_api
from cinder.volume.drivers.hitachi import hbsd_utils as utils
from cinder.volume.drivers.san import san
from cinder.volume import volume_utils

_GROUP_NAME_PROHIBITED_CHAR_PATTERN = re.compile(
    '[^' + common.GROUP_NAME_ALLOWED_CHARS + ']')

_LU_PATH_DEFINED = ('B958', '015A')
NORMAL_STS = 'NML'
_LUN_TIMEOUT = 50
_LUN_RETRY_INTERVAL = 1
_RESTORE_TIMEOUT = 24 * 60 * 60
_STATE_TRANSITION_TIMEOUT = 15 * 60

_CHECK_LDEV_MANAGEABILITY_KEYS = (
    'emulationType', 'numOfPorts', 'attributes', 'status')
_CHECK_LDEV_SIZE_KEYS = ('blockCapacity',)

SMPL = 1
PVOL = 2
SVOL = 3

COPY = 2
PAIR = 3
PSUS = 4
PSUE = 5
SMPP = 6
UNKN = 0xff

_STATUS_TABLE = {
    'SMPL': SMPL,
    'COPY': COPY,
    'RCPY': COPY,
    'PAIR': PAIR,
    'PFUL': PAIR,
    'PSUS': PSUS,
    'PFUS': PSUS,
    'SSUS': PSUS,
    'PSUE': PSUE,
    'PSUP': PSUS,
    'SSUP': PSUS,
    'SMPP': SMPP,
}

_SNAP_HASH_SIZE = 8

EX_ENOOBJ = 'EX_ENOOBJ'

_REST_DEFAULT_PORT = 443

_GET_LDEV_COUNT = 16384
_MAX_LDEV_ID = 65535
EX_ENLDEV = 'EX_ENLDEV'
EX_INVARG = 'EX_INVARG'
_INVALID_RANGE = [EX_ENLDEV, EX_INVARG]

_MAX_COPY_GROUP_NAME = 29
_MAX_CTG_COUNT_EXCEEDED_ADD_SNAPSHOT = ('2E10', '2302')
_MAX_PAIR_COUNT_IN_CTG_EXCEEDED_ADD_SNAPSHOT = ('2E13', '9900')

_PAIR_TARGET_NAME_BODY_DEFAULT = 'pair00'

_DR_VOL_PATTERN = {
    'disabled': ('REHYDRATING',),
    'compression_deduplication': ('ENABLED',),
    None: ('DELETING',),
}
_DISABLE_ABLE_DR_STATUS = {
    'disabled': ('DISABLED', 'ENABLING', 'REHYDRATING'),
    'compression_deduplication': ('ENABLED', 'ENABLING'),
}
_DEDUPCOMP_ABLE_DR_STATUS = {
    'disabled': ('DISABLED', 'ENABLING'),
    'compression_deduplication': ('ENABLED', 'ENABLING'),
}
_CAPACITY_SAVING_DR_MODE = {
    'disable': 'disabled',
    'deduplication_compression': 'compression_deduplication',
    '': 'disabled',
    None: 'disabled',
}

REST_VOLUME_OPTS = [
    cfg.BoolOpt(
        'hitachi_rest_disable_io_wait',
        default=True,
        help='This option will allow detaching volume immediately. '
             'If set False, storage may take few minutes to detach volume '
             'after I/O.'),
    cfg.BoolOpt(
        'hitachi_rest_tcp_keepalive',
        default=True,
        help='Enables or disables use of REST API tcp keepalive'),
    cfg.BoolOpt(
        'hitachi_discard_zero_page',
        default=True,
        help='Enable or disable zero page reclamation in a DP-VOL.'),
    cfg.IntOpt(
        'hitachi_lun_timeout',
        default=_LUN_TIMEOUT,
        help='Maximum wait time in seconds for adding a LUN mapping to '
             'the server.'),
    cfg.IntOpt(
        'hitachi_lun_retry_interval',
        default=_LUN_RETRY_INTERVAL,
        help='Retry interval in seconds for REST API adding a LUN mapping to '
             'the server.'),
    cfg.IntOpt(
        'hitachi_restore_timeout',
        default=_RESTORE_TIMEOUT,
        help='Maximum wait time in seconds for the restore operation to '
             'complete.'),
    cfg.IntOpt(
        'hitachi_state_transition_timeout',
        default=_STATE_TRANSITION_TIMEOUT,
        help='Maximum wait time in seconds for a volume transition to '
             'complete.'),
    cfg.IntOpt(
        'hitachi_lock_timeout',
        default=rest_api._LOCK_TIMEOUT,
        help='Maximum wait time in seconds for storage to be logined or '
             'unlocked.'),
    cfg.IntOpt(
        'hitachi_rest_timeout',
        default=rest_api._REST_TIMEOUT,
        help='Maximum wait time in seconds for each REST API request.'),
    cfg.IntOpt(
        'hitachi_extend_timeout',
        default=rest_api._EXTEND_TIMEOUT,
        help='Maximum wait time in seconds for a volume extention to '
             'complete.'),
    cfg.IntOpt(
        'hitachi_exec_retry_interval',
        default=rest_api._EXEC_RETRY_INTERVAL,
        help='Retry interval in seconds for REST API execution.'),
    cfg.IntOpt(
        'hitachi_rest_connect_timeout',
        default=rest_api._DEFAULT_CONNECT_TIMEOUT,
        help='Maximum wait time in seconds for connecting to '
             'REST API session.'),
    cfg.IntOpt(
        'hitachi_rest_job_api_response_timeout',
        default=rest_api._JOB_API_RESPONSE_TIMEOUT,
        help='Maximum wait time in seconds for a response against '
             'async methods from REST API, for example PUT and DELETE.'),
    cfg.IntOpt(
        'hitachi_rest_get_api_response_timeout',
        default=rest_api._GET_API_RESPONSE_TIMEOUT,
        help='Maximum wait time in seconds for a response against '
             'sync methods, for example GET'),
    cfg.IntOpt(
        'hitachi_rest_server_busy_timeout',
        default=rest_api._REST_SERVER_BUSY_TIMEOUT,
        help='Maximum wait time in seconds when REST API returns busy.'),
    cfg.IntOpt(
        'hitachi_rest_keep_session_loop_interval',
        default=rest_api._KEEP_SESSION_LOOP_INTERVAL,
        help='Loop interval in seconds for keeping REST API session.'),
    cfg.IntOpt(
        'hitachi_rest_another_ldev_mapped_retry_timeout',
        default=rest_api._ANOTHER_LDEV_MAPPED_RETRY_TIMEOUT,
        help='Retry time in seconds when new LUN allocation request fails.'),
    cfg.IntOpt(
        'hitachi_rest_tcp_keepidle',
        default=rest_api._TCP_KEEPIDLE,
        help='Wait time in seconds for sending a first TCP keepalive packet.'),
    cfg.IntOpt(
        'hitachi_rest_tcp_keepintvl',
        default=rest_api._TCP_KEEPINTVL,
        help='Interval of transmissions in seconds for TCP keepalive packet.'),
    cfg.IntOpt(
        'hitachi_rest_tcp_keepcnt',
        default=rest_api._TCP_KEEPCNT,
        help='Maximum number of transmissions for TCP keepalive packet.'),
    cfg.ListOpt(
        'hitachi_host_mode_options',
        item_type=types.Integer(),
        default=[],
        help='Host mode option for host group or iSCSI target.'),
]

REST_PAIR_OPTS = [
    cfg.ListOpt(
        'hitachi_rest_pair_target_ports',
        default=[],
        help='Target port names for pair of the host group or iSCSI target'),
]

_REQUIRED_REST_OPTS = [
    'san_login',
    'san_password',
    'san_ip',
]

CONF = cfg.CONF
CONF.register_opts(REST_VOLUME_OPTS, group=configuration.SHARED_CONF_GROUP)
CONF.register_opts(REST_PAIR_OPTS, group=configuration.SHARED_CONF_GROUP)

LOG = logging.getLogger(__name__)
MSG = utils.HBSDMsg


def _is_valid_target(self, target, target_name, target_ports, is_pair):
    """Check if the specified target is valid."""
    if is_pair:
        return (target[:utils.PORT_ID_LENGTH] in target_ports and
                target_name == self._PAIR_TARGET_NAME)
    return (target[:utils.PORT_ID_LENGTH] in target_ports and
            target_name.startswith(self.driver_info['target_prefix']) and
            target_name != self._PAIR_TARGET_NAME)


def _check_ldev_manageability(self, ldev_info, ldev, existing_ref):
    """Check if the LDEV meets the criteria for being managed."""
    if ldev_info['status'] != NORMAL_STS:
        msg = self.output_log(MSG.INVALID_LDEV_FOR_MANAGE)
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref, reason=msg)
    attributes = set(ldev_info['attributes'])
    if (not ldev_info['emulationType'].startswith('OPEN-V') or
            len(attributes) < 2 or
            not attributes.issubset(
                set(['CVS', self.driver_info['hdp_vol_attr'],
                     self.driver_info['hdt_vol_attr']]))):
        msg = self.output_log(MSG.INVALID_LDEV_ATTR_FOR_MANAGE, ldev=ldev,
                              ldevtype=self.driver_info['nvol_ldev_type'])
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref, reason=msg)
    if ldev_info['numOfPorts']:
        msg = self.output_log(MSG.INVALID_LDEV_PORT_FOR_MANAGE, ldev=ldev)
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref, reason=msg)


def _check_ldev_size(self, ldev_info, ldev, existing_ref):
    """Hitachi storage calculates volume sizes in a block unit, 512 bytes."""
    if ldev_info['blockCapacity'] % utils.GIGABYTE_PER_BLOCK_SIZE:
        msg = self.output_log(MSG.INVALID_LDEV_SIZE_FOR_MANAGE, ldev=ldev)
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref, reason=msg)


class HBSDREST(common.HBSDCommon):
    """REST interface class for Hitachi HBSD Driver."""

    def __init__(self, conf, storage_protocol, db):
        """Initialize instance variables."""
        super(HBSDREST, self).__init__(conf, storage_protocol, db)
        self.conf.append_config_values(REST_VOLUME_OPTS)
        self.conf.append_config_values(REST_PAIR_OPTS)
        self.conf.append_config_values(san.san_opts)

        self.client = None

    def do_setup(self, context):
        if hasattr(
                self.conf,
                self.driver_info['param_prefix'] + '_pair_target_number'):
            self._PAIR_TARGET_NAME_BODY = 'pair%02d' % (
                self.conf.safe_get(self.driver_info['param_prefix'] +
                                   '_pair_target_number'))
        else:
            self._PAIR_TARGET_NAME_BODY = _PAIR_TARGET_NAME_BODY_DEFAULT
        self._PAIR_TARGET_NAME = (self.driver_info['target_prefix'] +
                                  self._PAIR_TARGET_NAME_BODY)
        super(HBSDREST, self).do_setup(context)

    def setup_client(self):
        """Initialize RestApiClient."""
        verify = self.conf.driver_ssl_cert_verify
        if verify:
            verify_path = self.conf.safe_get('driver_ssl_cert_path')
            if verify_path:
                verify = verify_path
        self.verify = verify
        is_rep = False
        if self.storage_id is not None:
            is_rep = True
        self.client = rest_api.RestApiClient(
            self.conf,
            self.conf.san_ip,
            self.conf.san_api_port,
            self.conf.hitachi_storage_id,
            self.conf.san_login,
            self.conf.san_password,
            self.driver_info['driver_prefix'],
            tcp_keepalive=self.conf.hitachi_rest_tcp_keepalive,
            verify=verify,
            is_rep=is_rep)
        self.client.login()

    def need_client_setup(self):
        """Check if the making of the communication client is necessary."""
        return not self.client or not self.client.get_my_session()

    def enter_keep_session(self):
        """Begin the keeping of the session."""
        if self.client is not None:
            self.client.enter_keep_session()

    def _set_dr_mode(self, body, capacity_saving):
        dr_mode = _CAPACITY_SAVING_DR_MODE.get(capacity_saving)
        if not dr_mode:
            msg = self.output_log(
                MSG.INVALID_EXTRA_SPEC_KEY,
                key=self.driver_info['driver_dir_name'] + ':capacity_saving',
                value=capacity_saving)
            self.raise_error(msg)
        body['dataReductionMode'] = dr_mode

    def _create_ldev_on_storage(self, size, extra_specs, pool_id, ldev_range):
        """Create an LDEV on the storage system."""
        body = {
            'byteFormatCapacity': '%sG' % size,
            'poolId': pool_id,
            'isParallelExecutionEnabled': True,
        }
        capacity_saving = None
        if self.driver_info.get('driver_dir_name'):
            capacity_saving = extra_specs.get(
                self.driver_info['driver_dir_name'] + ':capacity_saving')
        if capacity_saving:
            self._set_dr_mode(body, capacity_saving)
        if self.storage_info['ldev_range']:
            min_ldev, max_ldev = self.storage_info['ldev_range'][:2]
            body['startLdevId'] = min_ldev
            body['endLdevId'] = max_ldev
        return self.client.add_ldev(body, no_log=True)

    def set_qos_specs(self, ldev, qos_specs):
        self.client.set_qos_specs(ldev, qos_specs)

    def create_ldev(self, size, extra_specs, pool_id, ldev_range,
                    qos_specs=None):
        """Create an LDEV of the specified size and the specified type."""
        ldev = self._create_ldev_on_storage(
            size, extra_specs, pool_id, ldev_range)
        LOG.debug('Created logical device. (LDEV: %s)', ldev)
        if qos_specs:
            try:
                self.set_qos_specs(ldev, qos_specs)
            except Exception:
                with excutils.save_and_reraise_exception():
                    try:
                        self.delete_ldev(ldev)
                    except exception.VolumeDriverException:
                        self.output_log(MSG.DELETE_LDEV_FAILED, ldev=ldev)
        return ldev

    def modify_ldev_name(self, ldev, name):
        """Modify LDEV name."""
        body = {'label': name}
        self.client.modify_ldev(ldev, body)

    def delete_ldev_from_storage(self, ldev):
        """Delete the specified LDEV from the storage."""
        result = self.get_ldev_info(['emulationType',
                                     'dataReductionMode',
                                     'dataReductionStatus'], ldev)
        if result['dataReductionStatus'] == 'FAILED':
            msg = self.output_log(
                MSG.CONSISTENCY_NOT_GUARANTEE, ldev=ldev)
            self.raise_error(msg)
        if result['dataReductionStatus'] in _DR_VOL_PATTERN.get(
                result['dataReductionMode'], ()):
            body = {'isDataReductionDeleteForceExecute': True}
        else:
            body = None
        if result['emulationType'] == 'NOT DEFINED':
            self.output_log(MSG.LDEV_NOT_EXIST, ldev=ldev)
            return
        self.client.delete_ldev(
            ldev, body,
            timeout_message=(MSG.LDEV_DELETION_WAIT_TIMEOUT, {'ldev': ldev}))

    def _get_snap_pool_id(self, pvol):
        return (
            self.storage_info['snap_pool_id']
            if self.storage_info['snap_pool_id'] is not None
            else self.get_ldev_info(['poolId'], pvol)['poolId'])

    def _get_copy_pair_status(self, ldev):
        """Return the status of the volume in a copy pair."""
        params_s = {"svolLdevId": ldev}
        result_s = self.client.get_snapshots(params_s)
        if not result_s:
            params_p = {"pvolLdevId": ldev}
            result_p = self.client.get_snapshots(params_p)
            if not result_p:
                return SMPL
            return _STATUS_TABLE.get(result_p[0]['status'], UNKN)
        return _STATUS_TABLE.get(result_s[0]['status'], UNKN)

    def _wait_copy_pair_status(self, ldev, status, **kwargs):
        """Wait until the S-VOL status changes to the specified status."""
        interval = kwargs.pop(
            'interval', self.conf.hitachi_copy_check_interval)
        timeout = kwargs.pop(
            'timeout', self.conf.hitachi_state_transition_timeout)

        def _wait_for_copy_pair_status(
                start_time, ldev, status, timeout):
            """Raise True if the S-VOL is in the specified status."""
            if not isinstance(status, set):
                status = set([status])
            if self._get_copy_pair_status(ldev) in status:
                raise loopingcall.LoopingCallDone()
            if utils.timed_out(start_time, timeout):
                raise loopingcall.LoopingCallDone(False)

        loop = loopingcall.FixedIntervalLoopingCall(
            _wait_for_copy_pair_status, timeutils.utcnow(),
            ldev, status, timeout)
        if not loop.start(interval=interval).wait():
            msg = self.output_log(
                MSG.PAIR_STATUS_WAIT_TIMEOUT, svol=ldev)
            self.raise_error(msg)

    def _create_snap_pair(self, pvol, svol):
        """Create a snapshot copy pair on the storage."""
        snapshot_name = '%(prefix)s%(svol)s' % {
            'prefix': self.driver_info['driver_prefix'] + '-snap',
            'svol': svol % _SNAP_HASH_SIZE,
        }
        try:
            body = {"snapshotGroupName": snapshot_name,
                    "snapshotPoolId": self._get_snap_pool_id(pvol),
                    "pvolLdevId": pvol,
                    "svolLdevId": svol,
                    "autoSplit": True,
                    "canCascade": True,
                    "isDataReductionForceCopy": True}
            self.client.add_snapshot(body)
        except exception.VolumeDriverException as ex:
            if (utils.safe_get_err_code(ex.kwargs.get('errobj')) ==
                    rest_api.INVALID_SNAPSHOT_POOL and
                    not self.conf.hitachi_snap_pool):
                msg = self.output_log(
                    MSG.INVALID_PARAMETER,
                    param=self.driver_info['param_prefix'] + '_snap_pool')
                self.raise_error(msg)
            else:
                raise
        try:
            self._wait_copy_pair_status(svol, PSUS)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self._delete_pair_from_storage(pvol, svol)
                except exception.VolumeDriverException:
                    self.output_log(
                        MSG.DELETE_PAIR_FAILED, pvol=pvol, svol=svol)

    def _create_clone_pair(self, pvol, svol, snap_pool_id):
        """Create a clone copy pair on the storage."""
        snapshot_name = '%(prefix)s%(svol)s' % {
            'prefix': self.driver_info['driver_prefix'] + '-clone',
            'svol': svol % _SNAP_HASH_SIZE,
        }
        try:
            if self.conf.hitachi_copy_speed <= 2:
                pace = 'slower'
            elif self.conf.hitachi_copy_speed == 3:
                pace = 'medium'
            else:
                pace = 'faster'
            body = {"snapshotGroupName": snapshot_name,
                    "snapshotPoolId": self._get_snap_pool_id(pvol),
                    "pvolLdevId": pvol,
                    "svolLdevId": svol,
                    "isClone": True,
                    "clonesAutomation": True,
                    "copySpeed": pace,
                    "isDataReductionForceCopy": True}
            self.client.add_snapshot(body)
        except exception.VolumeDriverException as ex:
            if (utils.safe_get_err_code(ex.kwargs.get('errobj')) ==
                    rest_api.INVALID_SNAPSHOT_POOL and
                    not self.conf.hitachi_snap_pool):
                msg = self.output_log(
                    MSG.INVALID_PARAMETER,
                    param=self.driver_info['param_prefix'] + '_snap_pool')
                self.raise_error(msg)
            else:
                raise
        try:
            self._wait_copy_pair_status(svol, set([PSUS, SMPP, SMPL]))
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self._delete_pair_from_storage(pvol, svol)
                except exception.VolumeDriverException:
                    self.output_log(
                        MSG.DELETE_PAIR_FAILED, pvol=pvol, svol=svol)

    def create_pair_on_storage(
            self, pvol, svol, snap_pool_id, is_snapshot=False):
        """Create a copy pair on the storage."""
        if is_snapshot:
            self._create_snap_pair(pvol, svol)
        else:
            self._create_clone_pair(pvol, svol, snap_pool_id)

    def get_ldev_info(self, keys, ldev, **kwargs):
        """Return a dictionary of LDEV-related items.

        :param keys: LDEV Attributes to be obtained. Specify None to obtain all
        LDEV attributes.
        :type keys: list or NoneType
        :param int ldev: The LDEV ID
        :param dict kwargs: REST API options
        :return: LDEV info
        :rtype: dict
        """
        d = {}
        result = self.client.get_ldev(ldev, **kwargs)
        if not keys:
            # To avoid KeyError when accessing a missing attribute, set the
            # default value to None.
            return defaultdict(lambda: None, result)
        for key in keys:
            d[key] = result.get(key)
        return d

    def _wait_copy_pair_deleting(self, ldev, **kwargs):
        """Wait until the LDEV is no longer in a copy pair."""
        interval = kwargs.pop(
            'interval', self.conf.hitachi_async_copy_check_interval)

        def _wait_for_copy_pair_smpl(start_time, ldev):
            """Raise True if the LDEV is no longer in a copy pair."""
            ldev_info = self.get_ldev_info(['status', 'attributes'], ldev)
            if (ldev_info['status'] != NORMAL_STS or
                    self.driver_info['pair_attr'] not in
                    ldev_info['attributes']):
                raise loopingcall.LoopingCallDone()
            if utils.timed_out(
                    start_time, self.conf.hitachi_state_transition_timeout):
                raise loopingcall.LoopingCallDone(False)

        loop = loopingcall.FixedIntervalLoopingCall(
            _wait_for_copy_pair_smpl, timeutils.utcnow(), ldev)
        if not loop.start(interval=interval).wait():
            msg = self.output_log(
                MSG.PAIR_STATUS_WAIT_TIMEOUT, svol=ldev)
            self.raise_error(msg)

    def _delete_pair_from_storage(self, pvol, svol):
        """Disconnect the volume pair that consists of the specified LDEVs."""
        params_s = {"svolLdevId": svol}
        result = self.client.get_snapshots(params_s)
        if not result:
            return
        mun = result[0]['muNumber']
        # If the snapshot is in deleting status,
        # not need to call a delete operation.
        if _STATUS_TABLE.get(result[0]['status']) != SMPP:
            self.client.unassign_snapshot_volume(pvol, mun,
                                                 ignore_all_errors=True)
            ignore_return_code = [EX_ENOOBJ]
            self.client.delete_snapshot(
                pvol, mun, ignore_return_code=ignore_return_code)
        self._wait_copy_pair_deleting(svol)

    def _get_pair_ports(self):
        return (self.storage_info['pair_ports'] or
                self.storage_info['controller_ports'])

    def terminate_pair_connection(self, ldev):
        targets = {
            'list': [],
        }
        ldev_info = self.get_ldev_info(['status', 'attributes'], ldev)
        if (ldev_info['status'] == NORMAL_STS and
                self.driver_info['mirror_attr'] in ldev_info['attributes']):
            LOG.debug(
                'The specified LDEV has replication pair. '
                'Therefore, unmapping operation was skipped. '
                '(LDEV: %(ldev)s, vol_attr: %(info)s)',
                {'ldev': ldev, 'info': ldev_info['attributes']})
            return
        self._find_mapped_targets_from_storage(
            targets, ldev, self._get_pair_ports(), is_pair=True)
        self.unmap_ldev(targets, ldev)

    def delete_pair_based_on_svol(self, pvol, svol_info):
        """Disconnect all volume pairs to which the specified S-VOL belongs."""
        # If the pair status does not satisfy the execution condition,
        if not (svol_info['is_psus'] or
                _STATUS_TABLE.get(svol_info['status']) == SMPP):
            self.output_log(
                MSG.UNABLE_TO_DELETE_PAIR, pvol=pvol, svol=svol_info['ldev'])
            self.raise_busy()

        self._delete_pair_from_storage(pvol, svol_info['ldev'])
        if hasattr(
                self.conf,
                self.driver_info['param_prefix'] + '_rest_pair_target_ports'):
            self.terminate_pair_connection(svol_info['ldev'])
            self.terminate_pair_connection(pvol)

    def check_param(self):
        """Check parameter values and consistency among them."""
        super(HBSDREST, self).check_param()
        self.check_opts(self.conf, REST_VOLUME_OPTS)
        self.check_opts(self.conf, san.san_opts)
        if hasattr(
                self.conf,
                self.driver_info['param_prefix'] + '_rest_pair_target_ports'):
            self.check_opts(self.conf, REST_PAIR_OPTS)
            if (not self.conf.hitachi_target_ports and
                    not self.conf.hitachi_rest_pair_target_ports):
                msg = self.output_log(
                    MSG.INVALID_PARAMETER,
                    param=self.driver_info['param_prefix'] +
                    '_target_ports or ' + self.driver_info['param_prefix'] +
                    '_rest_pair_target_ports')
                self.raise_error(msg)
        LOG.debug(
            'Setting ldev_range: %s', self.storage_info['ldev_range'])
        for opt in _REQUIRED_REST_OPTS:
            if not self.conf.safe_get(opt):
                msg = self.output_log(MSG.INVALID_PARAMETER, param=opt)
                self.raise_error(msg)
        if not self.conf.safe_get('san_api_port'):
            self.conf.san_api_port = _REST_DEFAULT_PORT

    def _find_lun(self, ldev, port, gid):
        """Get LUN using."""
        luns_info = self.client.get_luns(port, gid)
        for lun_info in luns_info:
            if lun_info['ldevId'] == ldev:
                return lun_info['lun']
        return None

    def _run_add_lun(self, ldev, port, gid, lun=None):
        """Create a LUN between the specified LDEV and port-gid."""
        ignore_error = [_LU_PATH_DEFINED]
        if lun is not None:
            ignore_error = [rest_api.ANOTHER_LDEV_MAPPED]
        assigned_lun, errobj = self.client.add_lun(
            port, gid, ldev, lun=lun,
            ignore_error=ignore_error,
            interval=self.conf.hitachi_lun_retry_interval,
            timeout=self.conf.hitachi_lun_timeout)
        err_code = utils.safe_get_err_code(errobj)
        if lun is None:
            if err_code == _LU_PATH_DEFINED:
                lun = self._find_lun(ldev, port, gid)
                LOG.debug(
                    'An logical unit path has already defined in the '
                    'specified logical device. (LDEV: %(ldev)s, '
                    'port: %(port)s, gid: %(gid)s, lun: %(lun)s)',
                    {'ldev': ldev, 'port': port, 'gid': gid, 'lun': lun})
            else:
                lun = assigned_lun
        elif err_code == rest_api.ANOTHER_LDEV_MAPPED:
            self.output_log(MSG.MAP_LDEV_FAILED,
                            ldev=ldev, port=port, id=gid, lun=lun)
            return None
        LOG.debug(
            'Created logical unit path to the specified logical device. '
            '(LDEV: %(ldev)s, port: %(port)s, '
            'gid: %(gid)s, lun: %(lun)s)',
            {'ldev': ldev, 'port': port, 'gid': gid, 'lun': lun})
        return lun

    def map_ldev(self, targets, ldev, lun=None):
        """Create the path between the server and the LDEV and return LUN."""
        raise_err = False
        if lun is not None:
            head = 0
            raise_err = True
        else:
            head = 1
            port, gid = targets['list'][0]
            lun = self._run_add_lun(ldev, port, gid)
            targets['lun'][port] = True
        for port, gid in targets['list'][head:]:
            # When multipath is configured, Nova compute expects that
            # target_lun define the same value in all storage target.
            # Therefore, it should use same value of lun in other target.
            try:
                lun2 = self._run_add_lun(ldev, port, gid, lun=lun)
                if lun2 is not None:
                    targets['lun'][port] = True
                    raise_err = False
            except exception.VolumeDriverException:
                self.output_log(MSG.MAP_LDEV_FAILED, ldev=ldev,
                                port=port, id=gid, lun=lun)
        if raise_err:
            msg = self.output_log(
                MSG.CONNECT_VOLUME_FAILED,
                ldev=ldev, reason='Failed to attach in all ports.')
            self.raise_error(msg)
        return lun

    def attach_ldev(
            self, volume, ldev, connector, is_snapshot, targets, lun=None):
        """Initialize connection between the server and the volume."""
        target_ports = self.get_target_ports(connector)
        target_ports = self.filter_target_ports(target_ports, volume,
                                                is_snapshot)
        if (self.find_targets_from_storage(
                targets, connector, target_ports) and
                self.conf.hitachi_group_create):
            self.create_mapping_targets(targets, connector, volume)

        self.require_target_existed(targets)

        targets['list'].sort()
        for port in target_ports:
            targets['lun'][port] = False
        return int(self.map_ldev(targets, ldev, lun))

    def _find_mapped_targets_from_storage(
            self, targets, ldev, target_ports, is_pair=False):
        """Update port-gid list for the specified LDEV."""
        ldev_info = self.get_ldev_info(['ports'], ldev)
        if not ldev_info['ports']:
            return
        for port_info in ldev_info['ports']:
            if _is_valid_target(self, port_info['portId'],
                                port_info['hostGroupName'],
                                target_ports, is_pair):
                targets['list'].append(port_info)

    def _get_unmap_targets_list(self, target_list, mapped_list):
        """Return a list of IDs of ports that need to be disconnected."""
        unmap_list = []
        for mapping_info in mapped_list:
            if ((mapping_info['portId'][:utils.PORT_ID_LENGTH],
                 mapping_info['hostGroupNumber'])
                    in target_list):
                unmap_list.append(mapping_info)
        return unmap_list

    def unmap_ldev(self, targets, ldev):
        """Delete the LUN between the specified LDEV and port-gid."""
        interval = self.conf.hitachi_lun_retry_interval
        ignore_return_code = [EX_ENOOBJ]
        ignore_message_id = [rest_api.MSGID_SPECIFIED_OBJECT_DOES_NOT_EXIST]
        timeout = self.conf.hitachi_state_transition_timeout
        for target in targets['list']:
            port = target['portId']
            gid = target['hostGroupNumber']
            lun = target['lun']
            self.client.delete_lun(port, gid, lun,
                                   interval=interval,
                                   ignore_return_code=ignore_return_code,
                                   ignore_message_id=ignore_message_id,
                                   timeout=timeout)
            LOG.debug(
                'Deleted logical unit path of the specified logical '
                'device. (LDEV: %(ldev)s, host group: %(target)s)',
                {'ldev': ldev, 'target': target})

    def _get_target_luns(self, target):
        """Get the LUN mapping information of the host group."""
        port = target['portId']
        gid = target['hostGroupNumber']
        mapping_list = []
        luns_info = self.client.get_luns(port, gid)
        if luns_info:
            for lun_info in luns_info:
                mapping_list.append((port, gid, lun_info['lun'],
                                     lun_info['ldevId']))
        return mapping_list

    def delete_target_from_storage(self, port, gid):
        """Delete the host group or the iSCSI target from the port."""
        result = 1
        try:
            self.client.delete_host_grp(port, gid)
            result = 0
        except exception.VolumeDriverException:
            self.output_log(MSG.DELETE_TARGET_FAILED, port=port, id=gid)
        else:
            LOG.debug(
                'Deleted target. (port: %(port)s, gid: %(gid)s)',
                {'port': port, 'gid': gid})
        return result

    def clean_mapping_targets(self, targets):
        """Delete the empty host group without LU."""
        deleted_targets = []
        for target in targets['list']:
            if not len(self._get_target_luns(target)):
                port = target['portId']
                gid = target['hostGroupNumber']
                ret = self.delete_target_from_storage(port, gid)
                if not ret:
                    deleted_targets.append(port)
        return deleted_targets

    def detach_ldev(self, volume, ldev, connector):
        """Terminate connection between the server and the volume."""
        targets = {
            'info': {},
            'list': [],
            'iqns': {},
        }
        mapped_targets = {
            'list': [],
        }
        unmap_targets = {}
        deleted_targets = []

        target_ports = self.get_target_ports(connector)
        self.find_targets_from_storage(targets, connector, target_ports)
        self._find_mapped_targets_from_storage(
            mapped_targets, ldev, target_ports)
        unmap_targets['list'] = self._get_unmap_targets_list(
            targets['list'], mapped_targets['list'])
        unmap_targets['list'].sort(
            reverse=True,
            key=lambda port: (port.get('portId'), port.get('hostGroupNumber')))
        self.unmap_ldev(unmap_targets, ldev)

        if self.conf.hitachi_group_delete:
            deleted_targets = self.clean_mapping_targets(unmap_targets)
        return deleted_targets

    def find_all_mapped_targets_from_storage(self, targets, ldev):
        """Add all port-gids connected with the LDEV to the list."""
        ldev_info = self.get_ldev_info(['ports'], ldev)
        if ldev_info['ports']:
            for port in ldev_info['ports']:
                targets['list'].append(port)

    def extend_ldev(self, ldev, old_size, new_size):
        """Extend the specified LDEV to the specified new size."""
        body = {"parameters": {"additionalByteFormatCapacity":
                               '%sG' % (new_size - old_size)}}
        self.client.extend_ldev(ldev, body)

    def get_pool_info(self, pool_id, result=None):
        """Return the total and free capacity of the storage pool."""
        if result is None:
            result = self.client.get_pool(
                pool_id, ignore_message_id=[
                    rest_api.MSGID_SPECIFIED_OBJECT_DOES_NOT_EXIST])

            if 'errorSource' in result:
                msg = self.output_log(MSG.POOL_NOT_FOUND, pool=pool_id)
                self.raise_error(msg)

        tp_cap = result['totalPoolCapacity'] // units.Ki
        ta_cap = result['availableVolumeCapacity'] // units.Ki
        tl_cap = result['totalLocatedCapacity'] // units.Ki
        return tp_cap, ta_cap, tl_cap

    def get_pool_infos(self, pool_ids):
        """Return the total and free capacity of the storage pools."""
        result = []
        try:
            result = self.client.get_pools()
        except exception.VolumeDriverException:
            self.output_log(MSG.POOL_INFO_RETRIEVAL_FAILED, pool='all')
        pool_infos = []
        for pool_id in pool_ids:
            for pool_data in result:
                if pool_data['poolId'] == pool_id:
                    cap_data = self.get_pool_info(pool_id, pool_data)
                    break
            else:
                self.output_log(MSG.POOL_NOT_FOUND, pool=pool_id)
                cap_data = None
            pool_infos.append(cap_data)
        return pool_infos

    def discard_zero_page(self, volume):
        """Return the volume's no-data pages to the storage pool."""
        if self.conf.hitachi_discard_zero_page:
            ldev = self.get_ldev(volume)
            try:
                self.client.discard_zero_page(ldev)
            except exception.VolumeDriverException:
                self.output_log(MSG.DISCARD_ZERO_PAGE_FAILED, ldev=ldev)

    def _get_copy_pair_info(self, ldev):
        """Return info of the copy pair."""
        params_p = {"pvolLdevId": ldev}
        result_p = self.client.get_snapshots(params_p)
        if result_p:
            is_psus = _STATUS_TABLE.get(result_p[0]['status']) == PSUS
            pvol, svol = ldev, int(result_p[0]['svolLdevId'])
            status = result_p[0]['status']
        else:
            params_s = {"svolLdevId": ldev}
            result_s = self.client.get_snapshots(params_s)
            if result_s:
                is_psus = _STATUS_TABLE.get(result_s[0]['status']) == PSUS
                pvol, svol = int(result_s[0]['pvolLdevId']), ldev
                status = result_s[0]['status']
            else:
                return None, None
        LOG.debug(
            'Copy pair status. (P-VOL: %(pvol)s, S-VOL: %(svol)s, '
            'status: %(status)s)',
            {'pvol': pvol, 'svol': svol, 'status': status})

        return pvol, [{'ldev': svol, 'is_psus': is_psus, 'status': status}]

    def get_pair_info(self, ldev, ldev_info=None):
        """Return info of the volume pair.

        :param int ldev: The LDEV ID
        :param dict ldev_info: LDEV info
        :return: TI pair info if the LDEV has TI pairs, None otherwise
        :rtype: dict or NoneType
        """
        pair_info = {}
        if ldev_info is None:
            ldev_info = self.get_ldev_info(['status', 'attributes'], ldev)
        if (ldev_info['status'] != NORMAL_STS or
                self.driver_info['pair_attr'] not in ldev_info['attributes']):
            return None

        pvol, svol_info = self._get_copy_pair_info(ldev)
        if svol_info and svol_info[0]['status'] in ('SMPP', 'PSUP'):
            self._wait_copy_pair_deleting(svol_info[0]['ldev'])
            return self.get_pair_info(ldev)
        if pvol is not None:
            pair_info['pvol'] = pvol
            pair_info.setdefault('svol_info', [])
            pair_info['svol_info'].extend(svol_info)

        return pair_info

    def get_ldev_by_name(self, name):
        """Get the LDEV number from the given name."""
        ignore_message_id = ['KART40044-E']
        ignore_return_code = _INVALID_RANGE
        if self.storage_info['ldev_range']:
            start, end = self.storage_info['ldev_range'][:2]
            if end - start + 1 > _GET_LDEV_COUNT:
                cnt = _GET_LDEV_COUNT
            else:
                cnt = end - start + 1
        else:
            start = 0
            end = _MAX_LDEV_ID
            cnt = _GET_LDEV_COUNT

        for current in range(start, end, cnt):
            params = {'headLdevId': current, 'ldevOption': 'dpVolume',
                      'count': cnt}
            ldev_list = self.client.get_ldevs(
                params, ignore_message_id=ignore_message_id,
                ignore_return_code=ignore_return_code)
            for ldev_data in ldev_list:
                if 'label' in ldev_data and name == ldev_data['label']:
                    return ldev_data['ldevId']
        return None

    def check_ldev_manageability(self, ldev, existing_ref):
        """Check if the LDEV meets the criteria for being managed."""
        ldev_info = self.get_ldev_info(
            _CHECK_LDEV_MANAGEABILITY_KEYS, ldev)
        _check_ldev_manageability(self, ldev_info, ldev, existing_ref)

    def get_ldev_size_in_gigabyte(self, ldev, existing_ref):
        """Return the size[GB] of the specified LDEV."""
        ldev_info = self.get_ldev_info(
            _CHECK_LDEV_SIZE_KEYS, ldev)
        _check_ldev_size(self, ldev_info, ldev, existing_ref)
        return ldev_info['blockCapacity'] / utils.GIGABYTE_PER_BLOCK_SIZE

    def _get_pool_id(self, pool_list, pool_name_or_id):
        """Get the pool id from specified name."""
        if pool_name_or_id.isdigit():
            return int(pool_name_or_id)
        if pool_list['pool_list'] is None:
            pool_list['pool_list'] = self.client.get_pools()
        for pool_data in pool_list['pool_list']:
            if pool_data['poolName'] == pool_name_or_id:
                return pool_data['poolId']
        msg = self.output_log(MSG.POOL_NOT_FOUND, pool=pool_name_or_id)
        self.raise_error(msg)

    def check_pool_id(self):
        """Check the pool id of hitachi_pools and hitachi_snap_pool."""
        pool_id_list = []
        pool_list = {'pool_list': None}

        for pool in self.conf.hitachi_pools:
            pool_id_list.append(self._get_pool_id(pool_list, pool))

        snap_pool = self.conf.hitachi_snap_pool
        if snap_pool is not None:
            self.storage_info['snap_pool_id'] = self._get_pool_id(
                pool_list, snap_pool)
        elif len(pool_id_list) == 1:
            self.storage_info['snap_pool_id'] = pool_id_list[0]

        self.storage_info['pool_id'] = pool_id_list

    def _to_hostgroup(self, port, gid):
        """Get a host group name from host group ID."""
        return self.client.get_host_grp(port, gid)['hostGroupName']

    def get_port_hostgroup_map(self, ldev_id):
        """Get the mapping of a port and host group."""
        hostgroups = defaultdict(list)
        ldev_info = self.get_ldev_info(['ports'], ldev_id)
        if not ldev_info['ports']:
            return hostgroups
        for port in ldev_info['ports']:
            portId = port["portId"]
            hostgroup = self._to_hostgroup(
                portId, port["hostGroupNumber"])
            hostgroups[portId].append(hostgroup)
        return hostgroups

    def check_pair_svol(self, ldev):
        """Check if the specified LDEV is S-VOL in a copy pair."""
        ldev_info = self.get_ldev_info(['status',
                                        'snapshotPoolId'], ldev)
        if ldev_info['status'] != NORMAL_STS:
            return False
        if ldev_info['snapshotPoolId'] is not None:
            _, svol_info = self._get_copy_pair_info(ldev)
            if svol_info and svol_info[0]['status'] in ('SMPP', 'PSUP'):
                self._wait_copy_pair_deleting(ldev)
                return False
            else:
                return True
        return False

    def restore_ldev(self, pvol, svol):
        """Restore a pair of the specified LDEV."""
        params_s = {"svolLdevId": svol}
        result = self.client.get_snapshots(params_s)
        mun = result[0]['muNumber']
        body = {"parameters": {"autoSplit": True}}
        self.client.restore_snapshot(pvol, mun, body)

        self._wait_copy_pair_status(
            svol, PSUS, timeout=self.conf.hitachi_restore_timeout,
            interval=self.conf.hitachi_async_copy_check_interval)

    def has_snap_pair(self, pvol, svol):
        """Check if the volume have the pair of the snapshot."""
        ldev_info = self.get_ldev_info(['status', 'attributes'], svol)
        if (ldev_info['status'] != NORMAL_STS or
                self.driver_info['pair_attr'] not in ldev_info['attributes']):
            return False
        params_s = {"svolLdevId": svol}
        result = self.client.get_snapshots(params_s)
        if not result:
            return False
        return (result[0]['primaryOrSecondary'] == "S-VOL" and
                int(result[0]['pvolLdevId']) == pvol)

    def create_group(self):
        return None

    def _delete_group(self, group, objs, is_snapshot):
        model_update = {'status': group.status}
        objs_model_update = []
        events = []

        def _delete_group_obj(group, obj, is_snapshot):
            obj_update = {'id': obj.id}
            try:
                if is_snapshot:
                    self.delete_snapshot(obj)
                else:
                    self.delete_volume(obj)
                obj_update['status'] = 'deleted'
            except (exception.VolumeDriverException, exception.VolumeIsBusy,
                    exception.SnapshotIsBusy) as exc:
                obj_update['status'] = 'available' if isinstance(
                    exc, (exception.VolumeIsBusy,
                          exception.SnapshotIsBusy)) else 'error'
                self.output_log(
                    MSG.GROUP_OBJECT_DELETE_FAILED,
                    obj='snapshot' if is_snapshot else 'volume',
                    group='group snapshot' if is_snapshot else 'group',
                    group_id=group.id, obj_id=obj.id, ldev=self.get_ldev(obj),
                    reason=exc.msg)
            raise loopingcall.LoopingCallDone(obj_update)

        for obj in objs:
            loop = loopingcall.FixedIntervalLoopingCall(
                _delete_group_obj, group, obj, is_snapshot)
            event = loop.start(interval=0)
            events.append(event)
        for e in events:
            obj_update = e.wait()
            if obj_update['status'] != 'deleted':
                model_update['status'] = 'error'
            objs_model_update.append(obj_update)
        return model_update, objs_model_update

    def delete_group(self, group, volumes):
        return self._delete_group(group, volumes, False)

    def delete_group_snapshot(self, group_snapshot, snapshots):
        return self._delete_group(group_snapshot, snapshots, True)

    def create_group_from_src(
            self, context, group, volumes, snapshots=None, source_vols=None):
        volumes_model_update = []
        new_ldevs = []
        events = []

        def _create_group_volume_from_src(context, volume, src, from_snapshot):
            volume_model_update = {'id': volume.id}
            try:
                ldev = self.get_ldev(src)
                if ldev is None:
                    msg = self.output_log(
                        MSG.INVALID_LDEV_FOR_VOLUME_COPY,
                        type='snapshot' if from_snapshot else 'volume',
                        id=src.id)
                    self.raise_error(msg)
                volume_model_update.update(
                    self.create_volume_from_snapshot(volume, src) if
                    from_snapshot else self.create_cloned_volume(volume,
                                                                 src))
            except Exception as exc:
                volume_model_update['msg'] = utils.get_exception_msg(exc)
            raise loopingcall.LoopingCallDone(volume_model_update)

        try:
            from_snapshot = True if snapshots else False
            for volume, src in zip(volumes,
                                   snapshots if snapshots else source_vols):
                loop = loopingcall.FixedIntervalLoopingCall(
                    _create_group_volume_from_src, context, volume, src,
                    from_snapshot)
                event = loop.start(interval=0)
                events.append(event)
            is_success = True
            for e in events:
                volume_model_update = e.wait()
                if 'msg' in volume_model_update:
                    is_success = False
                    msg = volume_model_update['msg']
                else:
                    volumes_model_update.append(volume_model_update)
                ldev = self.get_ldev(volume_model_update)
                if ldev is not None:
                    new_ldevs.append(ldev)
            if not is_success:
                self.raise_error(msg)
        except Exception:
            with excutils.save_and_reraise_exception():
                for new_ldev in new_ldevs:
                    try:
                        self.delete_ldev(new_ldev)
                    except exception.VolumeDriverException:
                        self.output_log(MSG.DELETE_LDEV_FAILED, ldev=new_ldev)
        return None, volumes_model_update

    def update_group(self, group, add_volumes=None):
        if add_volumes and volume_utils.is_group_a_cg_snapshot_type(group):
            for volume in add_volumes:
                ldev = self.get_ldev(volume)
                if ldev is None:
                    msg = self.output_log(MSG.LDEV_NOT_EXIST_FOR_ADD_GROUP,
                                          volume_id=volume.id,
                                          group='consistency group',
                                          group_id=group.id)
                    self.raise_error(msg)
        return None, None, None

    def _create_non_cgsnapshot(self, group_snapshot, snapshots):
        model_update = {'status': fields.GroupSnapshotStatus.AVAILABLE}
        snapshots_model_update = []
        events = []

        def _create_non_cgsnapshot_snapshot(group_snapshot, snapshot):
            snapshot_model_update = {'id': snapshot.id}
            try:
                snapshot_model_update.update(self.create_snapshot(snapshot))
                snapshot_model_update['status'] = (
                    fields.SnapshotStatus.AVAILABLE)
            except Exception:
                snapshot_model_update['status'] = fields.SnapshotStatus.ERROR
                self.output_log(
                    MSG.GROUP_SNAPSHOT_CREATE_FAILED,
                    group=group_snapshot.group_id,
                    group_snapshot=group_snapshot.id,
                    group_type=group_snapshot.group_type_id,
                    volume=snapshot.volume_id, snapshot=snapshot.id)
            raise loopingcall.LoopingCallDone(snapshot_model_update)

        for snapshot in snapshots:
            loop = loopingcall.FixedIntervalLoopingCall(
                _create_non_cgsnapshot_snapshot, group_snapshot, snapshot)
            event = loop.start(interval=0)
            events.append(event)
        for e in events:
            snapshot_model_update = e.wait()
            if (snapshot_model_update['status'] ==
                    fields.SnapshotStatus.ERROR):
                model_update['status'] = fields.GroupSnapshotStatus.ERROR
            snapshots_model_update.append(snapshot_model_update)
        return model_update, snapshots_model_update

    def _create_ctg_snapshot_group_name(self, ldev):
        now = timeutils.utcnow()
        strnow = now.strftime("%y%m%d%H%M%S%f")
        ctg_name = '%(prefix)sC%(ldev)s%(time)s' % {
            'prefix': self.driver_info['driver_prefix'],
            'ldev': "{0:06X}".format(ldev),
            'time': strnow[:len(strnow) - 3],
        }
        return ctg_name[:_MAX_COPY_GROUP_NAME]

    def _delete_pairs_from_storage(self, pairs):
        for pair in pairs:
            try:
                self._delete_pair_from_storage(pair['pvol'], pair['svol'])
            except exception.VolumeDriverException:
                self.output_log(MSG.DELETE_PAIR_FAILED, pvol=pair['pvol'],
                                svol=pair['svol'])

    def _create_ctg_snap_pair(self, pairs):
        snapshotgroup_name = self._create_ctg_snapshot_group_name(
            pairs[0]['pvol'])
        try:
            for pair in pairs:
                try:
                    body = {"snapshotGroupName": snapshotgroup_name,
                            "snapshotPoolId": self._get_snap_pool_id(
                                pair['pvol']),
                            "pvolLdevId": pair['pvol'],
                            "svolLdevId": pair['svol'],
                            "isConsistencyGroup": True,
                            "canCascade": True,
                            "isDataReductionForceCopy": True}
                    self.client.add_snapshot(body)
                except exception.VolumeDriverException as ex:
                    if ((utils.safe_get_err_code(ex.kwargs.get('errobj')) ==
                         _MAX_CTG_COUNT_EXCEEDED_ADD_SNAPSHOT) or
                        (utils.safe_get_err_code(ex.kwargs.get('errobj')) ==
                         _MAX_PAIR_COUNT_IN_CTG_EXCEEDED_ADD_SNAPSHOT)):
                        msg = self.output_log(MSG.FAILED_CREATE_CTG_SNAPSHOT)
                        self.raise_error(msg)
                    elif (utils.safe_get_err_code(ex.kwargs.get('errobj')) ==
                            rest_api.INVALID_SNAPSHOT_POOL and
                            not self.conf.hitachi_snap_pool):
                        msg = self.output_log(
                            MSG.INVALID_PARAMETER,
                            param=self.driver_info['param_prefix'] +
                            '_snap_pool')
                        self.raise_error(msg)
                    raise
                self._wait_copy_pair_status(pair['svol'], PAIR)
            self.client.split_snapshotgroup(snapshotgroup_name)
            for pair in pairs:
                self._wait_copy_pair_status(pair['svol'], PSUS)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._delete_pairs_from_storage(pairs)

    def _create_cgsnapshot(self, context, cgsnapshot, snapshots):
        pairs = []
        events = []
        snapshots_model_update = []

        def _create_cgsnapshot_volume(snapshot):
            pair = {'snapshot': snapshot}
            try:
                pair['pvol'] = self.get_ldev(snapshot.volume)
                if pair['pvol'] is None:
                    msg = self.output_log(
                        MSG.INVALID_LDEV_FOR_VOLUME_COPY,
                        type='volume', id=snapshot.volume_id)
                    self.raise_error(msg)
                size = snapshot.volume_size
                pool_id = self.get_pool_id_of_volume(snapshot.volume)
                ldev_range = self.storage_info['ldev_range']
                extra_specs = self.get_volume_extra_specs(snapshot.volume)
                qos_specs = utils.get_qos_specs_from_volume(snapshot)
                pair['svol'] = self.create_ldev(size, extra_specs,
                                                pool_id, ldev_range,
                                                qos_specs=qos_specs)
                self.modify_ldev_name(pair['svol'],
                                      snapshot.id.replace("-", ""))
            except Exception as exc:
                pair['msg'] = utils.get_exception_msg(exc)
            raise loopingcall.LoopingCallDone(pair)

        try:
            for snapshot in snapshots:
                ldev = self.get_ldev(snapshot.volume)
                if ldev is None:
                    msg = self.output_log(
                        MSG.INVALID_LDEV_FOR_VOLUME_COPY, type='volume',
                        id=snapshot.volume_id)
                    self.raise_error(msg)
            for snapshot in snapshots:
                loop = loopingcall.FixedIntervalLoopingCall(
                    _create_cgsnapshot_volume, snapshot)
                event = loop.start(interval=0)
                events.append(event)
            is_success = True
            for e in events:
                pair = e.wait()
                if 'msg' in pair:
                    is_success = False
                    msg = pair['msg']
                pairs.append(pair)
            if not is_success:
                self.raise_error(msg)
            self._create_ctg_snap_pair(pairs)
        except Exception:
            for pair in pairs:
                if 'svol' in pair and pair['svol'] is not None:
                    try:
                        self.delete_ldev(pair['svol'])
                    except exception.VolumeDriverException:
                        self.output_log(
                            MSG.DELETE_LDEV_FAILED, ldev=pair['svol'])
            model_update = {'status': fields.GroupSnapshotStatus.ERROR}
            for snapshot in snapshots:
                snapshot_model_update = {'id': snapshot.id,
                                         'status': fields.SnapshotStatus.ERROR}
                snapshots_model_update.append(snapshot_model_update)
            return model_update, snapshots_model_update
        for pair in pairs:
            snapshot_model_update = {
                'id': pair['snapshot'].id,
                'status': fields.SnapshotStatus.AVAILABLE,
                'provider_location': str(pair['svol'])}
            snapshots_model_update.append(snapshot_model_update)
        return None, snapshots_model_update

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        if volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            return self._create_cgsnapshot(context, group_snapshot, snapshots)
        else:
            return self._create_non_cgsnapshot(group_snapshot, snapshots)

    def _init_pair_targets(self, targets_info):
        self._pair_targets = []
        for port in targets_info.keys():
            if not targets_info[port]:
                continue
            params = {'portId': port}
            host_grp_list = self.client.get_host_grps(params)
            gid = None
            for host_grp_data in host_grp_list:
                if host_grp_data['hostGroupName'] == self._PAIR_TARGET_NAME:
                    gid = host_grp_data['hostGroupNumber']
                    break
            if not gid:
                try:
                    connector = {
                        'ip': self._PAIR_TARGET_NAME_BODY,
                        'wwpns': [self._PAIR_TARGET_NAME_BODY],
                    }
                    target_name, gid = self.create_target_to_storage(
                        port, connector, None)
                    LOG.debug(
                        'Created host group for pair operation. '
                        '(port: %(port)s, gid: %(gid)s)',
                        {'port': port, 'gid': gid})
                except exception.VolumeDriverException:
                    self.output_log(MSG.CREATE_HOST_GROUP_FAILED, port=port)
                    continue
            self._pair_targets.append((port, gid))

        if not self._pair_targets:
            msg = self.output_log(MSG.PAIR_TARGET_FAILED)
            self.raise_error(msg)
        self._pair_targets.sort(reverse=True)
        LOG.debug('Setting pair_targets: %s', self._pair_targets)

    def init_cinder_hosts(self, **kwargs):
        targets = {
            'info': {},
            'list': [],
            'iqns': {},
            'target_map': {},
        }
        super(HBSDREST, self).init_cinder_hosts(targets=targets)
        if self.storage_info['pair_ports']:
            targets['info'] = {}
            ports = self._get_pair_ports()
            for port in ports:
                targets['info'][port] = True
        if hasattr(
                self.conf,
                self.driver_info['param_prefix'] + '_rest_pair_target_ports'):
            self._init_pair_targets(targets['info'])

    def initialize_pair_connection(self, ldev):
        port, gid = None, None

        for port, gid in self._pair_targets:
            try:
                targets = {
                    'info': {},
                    'list': [(port, gid)],
                    'lun': {},
                }
                return self.map_ldev(targets, ldev)
            except exception.VolumeDriverException:
                self.output_log(
                    MSG.MAP_LDEV_FAILED, ldev=ldev, port=port, id=gid,
                    lun=None)

        msg = self.output_log(MSG.MAP_PAIR_TARGET_FAILED, ldev=ldev)
        self.raise_error(msg)

    def migrate_volume(self, volume, host, new_type=None):
        """Migrate the specified volume."""
        attachments = volume.volume_attachment
        if attachments:
            return False, None

        pvol = self.get_ldev(volume)
        if pvol is None:
            msg = self.output_log(
                MSG.INVALID_LDEV_FOR_VOLUME_COPY, type='volume', id=volume.id)
            self.raise_error(msg)

        pair_info = self.get_pair_info(pvol)
        if pair_info:
            if pair_info['pvol'] == pvol:
                svols = []
                copy_methods = []
                svol_statuses = []
                for svol_info in pair_info['svol_info']:
                    svols.append(str(svol_info['ldev']))
                    copy_methods.append(utils.THIN)
                    svol_statuses.append(svol_info['status'])
                if svols:
                    pair_info = ['(%s, %s, %s, %s)' %
                                 (pvol, svol, copy_method, status)
                                 for svol, copy_method, status in
                                 zip(svols, copy_methods, svol_statuses)]
                    msg = self.output_log(
                        MSG.MIGRATE_VOLUME_FAILED,
                        volume=volume.id, ldev=pvol,
                        pair_info=', '.join(pair_info))
                    self.raise_error(msg)
            else:
                svol_info = pair_info['svol_info'][0]
                if svol_info['is_psus'] and svol_info['status'] != 'PSUP':
                    return False, None
                else:
                    pair_info = '(%s, %s, %s, %s)' % (
                        pair_info['pvol'], svol_info['ldev'],
                        utils.THIN, svol_info['status'])
                    msg = self.output_log(
                        MSG.MIGRATE_VOLUME_FAILED,
                        volume=volume.id, ldev=svol_info['ldev'],
                        pair_info=pair_info)
                    self.raise_error(msg)

        old_storage_id = self.conf.hitachi_storage_id
        new_storage_id = (
            host['capabilities']['location_info'].get('storage_id'))
        if new_type is None:
            old_pool_id = self.get_ldev_info(['poolId'], pvol)['poolId']
        new_pool_id = host['capabilities']['location_info'].get('pool_id')

        if old_storage_id != new_storage_id:
            return False, None

        ldev_range = host['capabilities']['location_info'].get('ldev_range')
        if (new_type or old_pool_id != new_pool_id or
                (ldev_range and
                 (pvol < ldev_range[0] or ldev_range[1] < pvol))):
            extra_specs = self.get_volume_extra_specs(volume)
            if new_type:
                qos_specs = utils.get_qos_specs_from_volume_type(new_type)
            else:
                qos_specs = utils.get_qos_specs_from_volume(volume)
            snap_pool_id = host['capabilities']['location_info'].get(
                'snap_pool_id')
            ldev_range = host['capabilities']['location_info'].get(
                'ldev_range')
            svol = self.copy_on_storage(
                pvol, volume.size, extra_specs, new_pool_id,
                snap_pool_id, ldev_range,
                is_snapshot=False, sync=True, qos_specs=qos_specs)
            self.modify_ldev_name(svol, volume['id'].replace("-", ""))

            try:
                self.delete_ldev(pvol)
            except exception.VolumeDriverException:
                self.output_log(MSG.DELETE_LDEV_FAILED, ldev=pvol)

            return True, {
                'provider_location': str(svol),
            }

        return True, None

    def _is_modifiable_dr_value(self, dr_mode, dr_status, new_dr_mode, volume):
        if (dr_status == 'REHYDRATING' and
                new_dr_mode == 'compression_deduplication'):
            self.output_log(MSG.VOLUME_IS_BEING_REHYDRATED,
                            volume_id=volume['id'],
                            volume_type=volume['volume_type']['name'])
            return False
        elif dr_status == 'FAILED':
            self.output_log(MSG.INCONSISTENCY_DEDUPLICATION_SYSTEM_VOLUME,
                            volume_id=volume['id'],
                            volume_type=volume['volume_type']['name'])
            return False
        elif new_dr_mode == 'disabled':
            return dr_status in _DISABLE_ABLE_DR_STATUS.get(dr_mode, ())
        elif new_dr_mode == 'compression_deduplication':
            return dr_status in _DEDUPCOMP_ABLE_DR_STATUS.get(dr_mode, ())
        return False

    def _modify_capacity_saving(self, ldev, capacity_saving):
        body = {'dataReductionMode': capacity_saving}
        self.client.modify_ldev(
            ldev, body,
            timeout_message=(
                MSG.NOT_COMPLETED_CHANGE_VOLUME_TYPE, {'ldev': ldev}))

    def retype(self, ctxt, volume, new_type, diff, host):
        """Retype the specified volume."""
        diff_items = []

        def _check_specs_diff(diff, allowed_extra_specs):
            for specs_key, specs_val in diff.items():
                if specs_key == 'qos_specs':
                    diff_items.append(specs_key)
                    continue
                for diff_key, diff_val in specs_val.items():
                    if (specs_key == 'extra_specs' and
                            diff_key in allowed_extra_specs):
                        diff_items.append(diff_key)
                        continue
                    if diff_val[0] != diff_val[1]:
                        return False
            return True

        extra_specs_capacity_saving = None
        new_capacity_saving = None
        allowed_extra_specs = []
        if self.driver_info.get('driver_dir_name'):
            extra_specs_capacity_saving = (
                self.driver_info['driver_dir_name'] + ':capacity_saving')
            new_capacity_saving = (
                new_type['extra_specs'].get(extra_specs_capacity_saving))
            allowed_extra_specs.append(extra_specs_capacity_saving)
        new_dr_mode = _CAPACITY_SAVING_DR_MODE.get(new_capacity_saving)
        if not new_dr_mode:
            msg = self.output_log(
                MSG.FAILED_CHANGE_VOLUME_TYPE,
                key=extra_specs_capacity_saving,
                value=new_capacity_saving)
            self.raise_error(msg)
        ldev = self.get_ldev(volume)
        if ldev is None:
            msg = self.output_log(
                MSG.INVALID_LDEV_FOR_VOLUME_COPY, type='volume',
                id=volume['id'])
            self.raise_error(msg)
        ldev_info = self.get_ldev_info(
            ['dataReductionMode', 'dataReductionStatus', 'poolId'], ldev)
        old_pool_id = ldev_info['poolId']
        new_pool_id = host['capabilities']['location_info'].get('pool_id')
        if (not _check_specs_diff(diff, allowed_extra_specs)
                or new_pool_id != old_pool_id):
            snaps = SnapshotList.get_all_for_volume(ctxt, volume.id)
            if not snaps:
                return self.migrate_volume(volume, host, new_type)
            return False

        if (extra_specs_capacity_saving
                and extra_specs_capacity_saving in diff_items):
            ldev_info = self.get_ldev_info(
                ['dataReductionMode', 'dataReductionStatus'], ldev)
            if not self._is_modifiable_dr_value(
                    ldev_info['dataReductionMode'],
                    ldev_info['dataReductionStatus'], new_dr_mode, volume):
                return False

            self._modify_capacity_saving(ldev, new_dr_mode)

        if 'qos_specs' in diff_items:
            old_qos_specs = self.get_qos_specs_from_ldev(ldev)
            new_qos_specs = utils.get_qos_specs_from_volume_type(new_type)
            if old_qos_specs != new_qos_specs:
                self.change_qos_specs(ldev, old_qos_specs, new_qos_specs)

        return True

    def wait_copy_completion(self, pvol, svol):
        """Wait until copy is completed."""
        self._wait_copy_pair_status(svol, set([SMPL, PSUE]))
        status = self._get_copy_pair_status(svol)
        if status == PSUE:
            msg = self.output_log(MSG.VOLUME_COPY_FAILED, pvol=pvol, svol=svol)
            self.raise_error(msg)

    def create_target_name(self, connector):
        if ('ip' in connector and connector['ip']
                == self._PAIR_TARGET_NAME_BODY):
            return self._PAIR_TARGET_NAME
        wwn = (min(self.get_hba_ids_from_connector(connector)) if
               self.format_info['group_name_var_cnt'][
                   common.GROUP_NAME_VAR_WWN] else '')
        ip = (connector['ip'] if self.format_info[
            'group_name_var_cnt'][common.GROUP_NAME_VAR_IP] else '')
        if not self.format_info['group_name_var_cnt'][
                common.GROUP_NAME_VAR_HOST]:
            return self.format_info['group_name_format'].format(wwn=wwn, ip=ip)
        host = connector['host'] if 'host' in connector else ''
        max_host_len = (self.group_name_format['group_name_max_len'] -
                        self.format_info['group_name_format_without_var_len'] -
                        len(wwn) - len(ip))
        host = _GROUP_NAME_PROHIBITED_CHAR_PATTERN.sub(
            '_', host[:max_host_len])
        return self.format_info['group_name_format'].format(
            host=host, wwn=wwn, ip=ip)

    def change_qos_specs(self, ldev, old_qos_specs, new_qos_specs):
        delete_specs = {key: 0 for key in old_qos_specs
                        if key in utils.QOS_KEYS}
        if delete_specs:
            self.client.set_qos_specs(ldev, delete_specs)
        if new_qos_specs:
            self.client.set_qos_specs(ldev, new_qos_specs)

    def get_qos_specs_from_ldev(self, ldev):
        params = {'detailInfoType': 'qos',
                  'headLdevId': ldev,
                  'count': 1}
        ldev_info = self.client.get_ldevs(params=params)[0]
        return ldev_info.get('qos', {})
