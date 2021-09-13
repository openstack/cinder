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
"""REST interface module for Hitachi HBSD Driver."""

from collections import defaultdict

from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import timeutils
from oslo_utils import units

from cinder import exception
from cinder.objects import fields
from cinder.volume import configuration
from cinder.volume.drivers.hitachi import hbsd_common as common
from cinder.volume.drivers.hitachi import hbsd_rest_api as rest_api
from cinder.volume.drivers.hitachi import hbsd_utils as utils
from cinder.volume.drivers.san import san
from cinder.volume import volume_utils

_LU_PATH_DEFINED = ('B958', '015A')
NORMAL_STS = 'NML'
_LUN_MAX_WAITTIME = 50
_LUN_RETRY_INTERVAL = 1
PAIR_ATTR = 'HTI'
_SNAP_MODE = 'A'
_CLONE_MODE = 'C'
_NORMAL_MODE = '-'

_PERMITTED_TYPES = set(['CVS', 'HDP', 'HDT'])

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

SNAP_NAME = 'HBSD-snap'
CLONE_NAME = 'HBSD-clone'

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

REST_VOLUME_OPTS = [
    cfg.BoolOpt(
        'hitachi_rest_tcp_keepalive',
        default=True,
        help='Enables or disables use of REST API tcp keepalive'),
    cfg.BoolOpt(
        'hitachi_discard_zero_page',
        default=True,
        help='Enable or disable zero page reclamation in a DP-VOL.'),
]

_REQUIRED_REST_OPTS = [
    'san_login',
    'san_password',
    'san_ip',
]

CONF = cfg.CONF
CONF.register_opts(REST_VOLUME_OPTS, group=configuration.SHARED_CONF_GROUP)

LOG = logging.getLogger(__name__)
MSG = utils.HBSDMsg


def _is_valid_target(target, target_name, target_ports):
    """Check if the specified target is valid."""
    return (target[:utils.PORT_ID_LENGTH] in target_ports and
            target_name.startswith(utils.TARGET_PREFIX))


def _check_ldev_manageability(ldev_info, ldev, existing_ref):
    """Check if the LDEV meets the criteria for being managed."""
    if ldev_info['status'] != NORMAL_STS:
        msg = utils.output_log(MSG.INVALID_LDEV_FOR_MANAGE)
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref, reason=msg)
    attributes = set(ldev_info['attributes'])
    if (not ldev_info['emulationType'].startswith('OPEN-V') or
            len(attributes) < 2 or not attributes.issubset(_PERMITTED_TYPES)):
        msg = utils.output_log(MSG.INVALID_LDEV_ATTR_FOR_MANAGE, ldev=ldev,
                               ldevtype=utils.NVOL_LDEV_TYPE)
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref, reason=msg)
    if ldev_info['numOfPorts']:
        msg = utils.output_log(MSG.INVALID_LDEV_PORT_FOR_MANAGE, ldev=ldev)
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref, reason=msg)


def _check_ldev_size(ldev_info, ldev, existing_ref):
    """Hitachi storage calculates volume sizes in a block unit, 512 bytes."""
    if ldev_info['blockCapacity'] % utils.GIGABYTE_PER_BLOCK_SIZE:
        msg = utils.output_log(MSG.INVALID_LDEV_SIZE_FOR_MANAGE, ldev=ldev)
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref, reason=msg)


class HBSDREST(common.HBSDCommon):
    """REST interface class for Hitachi HBSD Driver."""

    def __init__(self, conf, storage_protocol, db):
        """Initialize instance variables."""
        super(HBSDREST, self).__init__(conf, storage_protocol, db)
        self.conf.append_config_values(REST_VOLUME_OPTS)
        self.conf.append_config_values(san.san_opts)

        self.client = None

    def setup_client(self):
        """Initialize RestApiClient."""
        verify = self.conf.driver_ssl_cert_verify
        if verify:
            verify_path = self.conf.safe_get('driver_ssl_cert_path')
            if verify_path:
                verify = verify_path
        self.verify = verify
        self.client = rest_api.RestApiClient(
            self.conf.san_ip,
            self.conf.san_api_port,
            self.conf.hitachi_storage_id,
            self.conf.san_login,
            self.conf.san_password,
            tcp_keepalive=self.conf.hitachi_rest_tcp_keepalive,
            verify=verify)
        self.client.login()

    def need_client_setup(self):
        """Check if the making of the communication client is necessary."""
        return not self.client or not self.client.get_my_session()

    def enter_keep_session(self):
        """Begin the keeping of the session."""
        if self.client is not None:
            self.client.enter_keep_session()

    def _create_ldev_on_storage(self, size):
        """Create an LDEV on the storage system."""
        body = {
            'byteFormatCapacity': '%sG' % size,
            'poolId': self.storage_info['pool_id'],
            'isParallelExecutionEnabled': True,
        }
        if self.storage_info['ldev_range']:
            min_ldev, max_ldev = self.storage_info['ldev_range'][:2]
            body['startLdevId'] = min_ldev
            body['endLdevId'] = max_ldev
        return self.client.add_ldev(body, no_log=True)

    def create_ldev(self, size):
        """Create an LDEV of the specified size and the specified type."""
        ldev = self._create_ldev_on_storage(size)
        LOG.debug('Created logical device. (LDEV: %s)', ldev)
        return ldev

    def modify_ldev_name(self, ldev, name):
        """Modify LDEV name."""
        body = {'label': name}
        self.client.modify_ldev(ldev, body)

    def delete_ldev_from_storage(self, ldev):
        """Delete the specified LDEV from the storage."""
        result = self.client.get_ldev(ldev)
        if result['emulationType'] == 'NOT DEFINED':
            utils.output_log(MSG.LDEV_NOT_EXIST, ldev=ldev)
            return
        self.client.delete_ldev(
            ldev,
            timeout_message=(MSG.LDEV_DELETION_WAIT_TIMEOUT, {'ldev': ldev}))

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

    def _wait_copy_pair_status(self, ldev, status, interval=3,
                               timeout=utils.DEFAULT_PROCESS_WAITTIME):
        """Wait until the S-VOL status changes to the specified status."""

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
            msg = utils.output_log(
                MSG.PAIR_STATUS_WAIT_TIMEOUT, svol=ldev)
            raise utils.HBSDError(msg)

    def _create_snap_pair(self, pvol, svol):
        """Create a snapshot copy pair on the storage."""
        snapshot_name = '%(prefix)s%(svol)s' % {
            'prefix': SNAP_NAME,
            'svol': svol % _SNAP_HASH_SIZE,
        }
        try:
            body = {"snapshotGroupName": snapshot_name,
                    "snapshotPoolId": self.storage_info['snap_pool_id'],
                    "pvolLdevId": pvol,
                    "svolLdevId": svol,
                    "autoSplit": True,
                    "canCascade": True,
                    "isDataReductionForceCopy": True}
            self.client.add_snapshot(body)
        except utils.HBSDError as ex:
            if (utils.safe_get_err_code(ex.kwargs.get('errobj')) ==
                    rest_api.INVALID_SNAPSHOT_POOL and
                    not self.conf.hitachi_snap_pool):
                msg = utils.output_log(
                    MSG.INVALID_PARAMETER, param='hitachi_snap_pool')
                raise utils.HBSDError(msg)
            else:
                raise
        try:
            self._wait_copy_pair_status(svol, PSUS)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self._delete_pair_from_storage(pvol, svol)
                except utils.HBSDError:
                    utils.output_log(
                        MSG.DELETE_PAIR_FAILED, pvol=pvol, svol=svol)

    def _create_clone_pair(self, pvol, svol):
        """Create a clone copy pair on the storage."""
        snapshot_name = '%(prefix)s%(svol)s' % {
            'prefix': CLONE_NAME,
            'svol': svol % _SNAP_HASH_SIZE,
        }
        try:
            body = {"snapshotGroupName": snapshot_name,
                    "snapshotPoolId": self.storage_info['snap_pool_id'],
                    "pvolLdevId": pvol,
                    "svolLdevId": svol,
                    "isClone": True,
                    "clonesAutomation": True,
                    "copySpeed": 'medium',
                    "isDataReductionForceCopy": True}
            self.client.add_snapshot(body)
        except utils.HBSDError as ex:
            if (utils.safe_get_err_code(ex.kwargs.get('errobj')) ==
                    rest_api.INVALID_SNAPSHOT_POOL and
                    not self.conf.hitachi_snap_pool):
                msg = utils.output_log(
                    MSG.INVALID_PARAMETER, param='hitachi_snap_pool')
                raise utils.HBSDError(msg)
            else:
                raise
        try:
            self._wait_copy_pair_status(svol, set([PSUS, SMPP, SMPL]))
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self._delete_pair_from_storage(pvol, svol)
                except utils.HBSDError:
                    utils.output_log(
                        MSG.DELETE_PAIR_FAILED, pvol=pvol, svol=svol)

    def create_pair_on_storage(self, pvol, svol, is_snapshot=False):
        """Create a copy pair on the storage."""
        if is_snapshot:
            self._create_snap_pair(pvol, svol)
        else:
            self._create_clone_pair(pvol, svol)

    def get_ldev_info(self, keys, ldev, **kwargs):
        """Return a dictionary of LDEV-related items."""
        d = {}
        result = self.client.get_ldev(ldev, **kwargs)
        for key in keys:
            d[key] = result.get(key)
        return d

    def _wait_copy_pair_deleting(self, ldev):
        """Wait until the LDEV is no longer in a copy pair."""

        def _wait_for_copy_pair_smpl(start_time, ldev):
            """Raise True if the LDEV is no longer in a copy pair."""
            ldev_info = self.get_ldev_info(['status', 'attributes'], ldev)
            if (ldev_info['status'] != NORMAL_STS or
                    PAIR_ATTR not in ldev_info['attributes']):
                raise loopingcall.LoopingCallDone()
            if utils.timed_out(
                    start_time, utils.DEFAULT_PROCESS_WAITTIME):
                raise loopingcall.LoopingCallDone(False)

        loop = loopingcall.FixedIntervalLoopingCall(
            _wait_for_copy_pair_smpl, timeutils.utcnow(), ldev)
        if not loop.start(interval=10).wait():
            msg = utils.output_log(
                MSG.PAIR_STATUS_WAIT_TIMEOUT, svol=ldev)
            raise utils.HBSDError(msg)

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

    def delete_pair_based_on_svol(self, pvol, svol_info):
        """Disconnect all volume pairs to which the specified S-VOL belongs."""
        # If the pair status does not satisfy the execution condition,
        if not (svol_info['is_psus'] or
                _STATUS_TABLE.get(svol_info['status']) == SMPP):
            msg = utils.output_log(
                MSG.UNABLE_TO_DELETE_PAIR, pvol=pvol, svol=svol_info['ldev'])
            raise utils.HBSDBusy(msg)

        self._delete_pair_from_storage(pvol, svol_info['ldev'])

    def check_param(self):
        """Check parameter values and consistency among them."""
        super(HBSDREST, self).check_param()
        utils.check_opts(self.conf, REST_VOLUME_OPTS)
        utils.check_opts(self.conf, san.san_opts)
        LOG.debug(
            'Setting ldev_range: %s', self.storage_info['ldev_range'])
        for opt in _REQUIRED_REST_OPTS:
            if not self.conf.safe_get(opt):
                msg = utils.output_log(MSG.INVALID_PARAMETER, param=opt)
                raise utils.HBSDError(msg)
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
            interval=_LUN_RETRY_INTERVAL,
            timeout=_LUN_MAX_WAITTIME)
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
            utils.output_log(MSG.MAP_LDEV_FAILED,
                             ldev=ldev, port=port, id=gid, lun=lun)
            return None
        LOG.debug(
            'Created logical unit path to the specified logical device. '
            '(LDEV: %(ldev)s, port: %(port)s, '
            'gid: %(gid)s, lun: %(lun)s)',
            {'ldev': ldev, 'port': port, 'gid': gid, 'lun': lun})
        return lun

    def map_ldev(self, targets, ldev):
        """Create the path between the server and the LDEV and return LUN."""
        port, gid = targets['list'][0]
        lun = self._run_add_lun(ldev, port, gid)
        targets['lun'][port] = True
        for port, gid in targets['list'][1:]:
            # When multipath is configured, Nova compute expects that
            # target_lun define the same value in all storage target.
            # Therefore, it should use same value of lun in other target.
            try:
                lun2 = self._run_add_lun(ldev, port, gid, lun=lun)
                if lun2 is not None:
                    targets['lun'][port] = True
            except utils.HBSDError:
                utils.output_log(MSG.MAP_LDEV_FAILED, ldev=ldev,
                                 port=port, id=gid, lun=lun)
        return lun

    def attach_ldev(self, volume, ldev, connector, targets):
        """Initialize connection between the server and the volume."""
        target_ports = self.get_target_ports(connector)
        if (self.find_targets_from_storage(
                targets, connector, target_ports) and
                self.conf.hitachi_group_create):
            self.create_mapping_targets(targets, connector)

        utils.require_target_existed(targets)

        targets['list'].sort()
        for port in target_ports:
            targets['lun'][port] = False
        return int(self.map_ldev(targets, ldev))

    def _find_mapped_targets_from_storage(self, targets, ldev, target_ports):
        """Update port-gid list for the specified LDEV."""
        ldev_info = self.get_ldev_info(['ports'], ldev)
        if not ldev_info['ports']:
            return
        for port_info in ldev_info['ports']:
            if _is_valid_target(port_info['portId'],
                                port_info['hostGroupName'],
                                target_ports):
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
        interval = _LUN_RETRY_INTERVAL
        ignore_return_code = [EX_ENOOBJ]
        ignore_message_id = [rest_api.MSGID_SPECIFIED_OBJECT_DOES_NOT_EXIST]
        timeout = utils.DEFAULT_PROCESS_WAITTIME
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
        except utils.HBSDError:
            utils.output_log(MSG.DELETE_TARGET_FAILED, port=port, id=gid)
        else:
            LOG.debug(
                'Deleted target. (port: %(port)s, gid: %(gid)s)',
                {'port': port, 'gid': gid})
        return result

    def _clean_mapping_targets(self, targets):
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
            deleted_targets = self._clean_mapping_targets(unmap_targets)
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

    def get_pool_info(self):
        """Return the total and free capacity of the storage pool."""
        result = self.client.get_pool(
            self.storage_info['pool_id'],
            ignore_message_id=[rest_api.MSGID_SPECIFIED_OBJECT_DOES_NOT_EXIST])

        if 'errorSource' in result:
            msg = utils.output_log(MSG.POOL_NOT_FOUND,
                                   pool=self.storage_info['pool_id'])
            raise utils.HBSDError(msg)

        tp_cap = result['totalPoolCapacity'] / units.Ki
        ta_cap = result['availableVolumeCapacity'] / units.Ki
        tl_cap = result['totalLocatedCapacity'] / units.Ki

        return tp_cap, ta_cap, tl_cap

    def discard_zero_page(self, volume):
        """Return the volume's no-data pages to the storage pool."""
        if self.conf.hitachi_discard_zero_page:
            ldev = utils.get_ldev(volume)
            try:
                self.client.discard_zero_page(ldev)
            except utils.HBSDError:
                utils.output_log(MSG.DISCARD_ZERO_PAGE_FAILED, ldev=ldev)

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

    def get_pair_info(self, ldev):
        """Return info of the volume pair."""
        pair_info = {}
        ldev_info = self.get_ldev_info(['status', 'attributes'], ldev)
        if (ldev_info['status'] != NORMAL_STS or
                PAIR_ATTR not in ldev_info['attributes']):
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
        _check_ldev_manageability(ldev_info, ldev, existing_ref)

    def get_ldev_size_in_gigabyte(self, ldev, existing_ref):
        """Return the size[GB] of the specified LDEV."""
        ldev_info = self.get_ldev_info(
            _CHECK_LDEV_SIZE_KEYS, ldev)
        _check_ldev_size(ldev_info, ldev, existing_ref)
        return ldev_info['blockCapacity'] / utils.GIGABYTE_PER_BLOCK_SIZE

    def _get_pool_id(self, name):
        """Get the pool id from specified name."""
        pool_list = self.client.get_pools()
        for pool_data in pool_list:
            if pool_data['poolName'] == name:
                return pool_data['poolId']
        return None

    def check_pool_id(self):
        """Check the pool id of hitachi_pool and hitachi_snap_pool."""
        pool = self.conf.hitachi_pool
        if pool is not None:
            if pool.isdigit():
                self.storage_info['pool_id'] = int(pool)
            else:
                self.storage_info['pool_id'] = self._get_pool_id(pool)
        if self.storage_info['pool_id'] is None:
            msg = utils.output_log(
                MSG.POOL_NOT_FOUND, pool=self.conf.hitachi_pool)
            raise utils.HBSDError(msg)

        snap_pool = self.conf.hitachi_snap_pool
        if snap_pool is not None:
            if snap_pool.isdigit():
                self.storage_info['snap_pool_id'] = int(snap_pool)
            else:
                self.storage_info['snap_pool_id'] = (
                    self._get_pool_id(snap_pool))
                if self.storage_info['snap_pool_id'] is None:
                    msg = utils.output_log(MSG.POOL_NOT_FOUND,
                                           pool=self.conf.hitachi_snap_pool)
                    raise utils.HBSDError(msg)
        else:
            self.storage_info['snap_pool_id'] = self.storage_info['pool_id']

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
            if svol_info and svol_info[0]['status'] == 'PSUP':
                self._wait_copy_pair_deleting(ldev)
                return False
            else:
                return True
        return False

    def restore_ldev(self, pvol, svol):
        """Restore a pair of the specified LDEV."""
        timeout = utils.MAX_PROCESS_WAITTIME

        params_s = {"svolLdevId": svol}
        result = self.client.get_snapshots(params_s)
        mun = result[0]['muNumber']
        body = {"parameters": {"autoSplit": True}}
        self.client.restore_snapshot(pvol, mun, body)

        self._wait_copy_pair_status(
            svol, PSUS, timeout=timeout, interval=10)

    def has_snap_pair(self, pvol, svol):
        """Check if the volume have the pair of the snapshot."""
        ldev_info = self.get_ldev_info(['status', 'attributes'], svol)
        if (ldev_info['status'] != NORMAL_STS or
                PAIR_ATTR not in ldev_info['attributes']):
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
            except (utils.HBSDError, exception.VolumeIsBusy,
                    exception.SnapshotIsBusy) as exc:
                obj_update['status'] = 'available' if isinstance(
                    exc, (exception.VolumeIsBusy,
                          exception.SnapshotIsBusy)) else 'error'
                utils.output_log(
                    MSG.GROUP_OBJECT_DELETE_FAILED,
                    obj='snapshot' if is_snapshot else 'volume',
                    group='group snapshot' if is_snapshot else 'group',
                    group_id=group.id, obj_id=obj.id, ldev=utils.get_ldev(obj),
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
                ldev = utils.get_ldev(src)
                if ldev is None:
                    msg = utils.output_log(
                        MSG.INVALID_LDEV_FOR_VOLUME_COPY,
                        type='snapshot' if from_snapshot else 'volume',
                        id=src.id)
                    raise utils.HBSDError(msg)
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
                ldev = utils.get_ldev(volume_model_update)
                if ldev is not None:
                    new_ldevs.append(ldev)
            if not is_success:
                raise utils.HBSDError(msg)
        except Exception:
            with excutils.save_and_reraise_exception():
                for new_ldev in new_ldevs:
                    try:
                        self.delete_ldev(new_ldev)
                    except utils.HBSDError:
                        utils.output_log(MSG.DELETE_LDEV_FAILED, ldev=new_ldev)
        return None, volumes_model_update

    def update_group(self, group, add_volumes=None):
        if add_volumes and volume_utils.is_group_a_cg_snapshot_type(group):
            for volume in add_volumes:
                ldev = utils.get_ldev(volume)
                if ldev is None:
                    msg = utils.output_log(MSG.LDEV_NOT_EXIST_FOR_ADD_GROUP,
                                           volume_id=volume.id,
                                           group='consistency group',
                                           group_id=group.id)
                    raise utils.HBSDError(msg)
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
                utils.output_log(
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
            'prefix': utils.DRIVER_PREFIX,
            'ldev': "{0:06X}".format(ldev),
            'time': strnow[:len(strnow) - 3],
        }
        return ctg_name[:_MAX_COPY_GROUP_NAME]

    def _delete_pairs_from_storage(self, pairs):
        for pair in pairs:
            try:
                self._delete_pair_from_storage(pair['pvol'], pair['svol'])
            except utils.HBSDError:
                utils.output_log(MSG.DELETE_PAIR_FAILED, pvol=pair['pvol'],
                                 svol=pair['svol'])

    def _create_ctg_snap_pair(self, pairs):
        snapshotgroup_name = self._create_ctg_snapshot_group_name(
            pairs[0]['pvol'])
        try:
            for pair in pairs:
                try:
                    body = {"snapshotGroupName": snapshotgroup_name,
                            "snapshotPoolId":
                                self.storage_info['snap_pool_id'],
                            "pvolLdevId": pair['pvol'],
                            "svolLdevId": pair['svol'],
                            "isConsistencyGroup": True,
                            "canCascade": True,
                            "isDataReductionForceCopy": True}
                    self.client.add_snapshot(body)
                except utils.HBSDError as ex:
                    if ((utils.safe_get_err_code(ex.kwargs.get('errobj')) ==
                         _MAX_CTG_COUNT_EXCEEDED_ADD_SNAPSHOT) or
                        (utils.safe_get_err_code(ex.kwargs.get('errobj')) ==
                         _MAX_PAIR_COUNT_IN_CTG_EXCEEDED_ADD_SNAPSHOT)):
                        msg = utils.output_log(MSG.FAILED_CREATE_CTG_SNAPSHOT)
                        raise utils.HBSDError(msg)
                    elif (utils.safe_get_err_code(ex.kwargs.get('errobj')) ==
                            rest_api.INVALID_SNAPSHOT_POOL and
                            not self.conf.hitachi_snap_pool):
                        msg = utils.output_log(
                            MSG.INVALID_PARAMETER, param='hitachi_snap_pool')
                        raise utils.HBSDError(msg)
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
                pair['pvol'] = utils.get_ldev(snapshot.volume)
                if pair['pvol'] is None:
                    msg = utils.output_log(
                        MSG.INVALID_LDEV_FOR_VOLUME_COPY,
                        type='volume', id=snapshot.volume_id)
                    raise utils.HBSDError(msg)
                size = snapshot.volume_size
                pair['svol'] = self.create_ldev(size)
            except Exception as exc:
                pair['msg'] = utils.get_exception_msg(exc)
            raise loopingcall.LoopingCallDone(pair)

        try:
            for snapshot in snapshots:
                ldev = utils.get_ldev(snapshot.volume)
                if ldev is None:
                    msg = utils.output_log(
                        MSG.INVALID_LDEV_FOR_VOLUME_COPY, type='volume',
                        id=snapshot.volume_id)
                    raise utils.HBSDError(msg)
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
                raise utils.HBSDError(msg)
            self._create_ctg_snap_pair(pairs)
        except Exception:
            for pair in pairs:
                if 'svol' in pair and pair['svol'] is not None:
                    try:
                        self.delete_ldev(pair['svol'])
                    except utils.HBSDError:
                        utils.output_log(
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
