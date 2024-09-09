# Copyright (C) 2022, 2024, Hitachi, Ltd.
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
"""replication module for Hitachi HBSD Driver."""

from collections import defaultdict
import json

from eventlet import greenthread
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import timeutils

from cinder import exception
from cinder.volume.drivers.hitachi import hbsd_common as common
from cinder.volume.drivers.hitachi import hbsd_rest as rest
from cinder.volume.drivers.hitachi import hbsd_utils as utils
from cinder.zonemanager import utils as fczm_utils

_REP_STATUS_CHECK_SHORT_INTERVAL = 5
_REP_STATUS_CHECK_LONG_INTERVAL = 10 * 60
_REP_STATUS_CHECK_TIMEOUT = 24 * 60 * 60

_WAIT_PAIR = 1
_WAIT_PSUS = 2

_REP_OPTS = [
    cfg.IntOpt(
        'hitachi_replication_status_check_short_interval',
        default=_REP_STATUS_CHECK_SHORT_INTERVAL,
        help='Initial interval at which remote replication pair status is '
        'checked'),
    cfg.IntOpt(
        'hitachi_replication_status_check_long_interval',
        default=_REP_STATUS_CHECK_LONG_INTERVAL,
        help='Interval at which remote replication pair status is checked. '
        'This parameter is applied if the status has not changed to the '
        'expected status after the time indicated by this parameter has '
        'elapsed.'),
    cfg.IntOpt(
        'hitachi_replication_status_check_timeout',
        default=_REP_STATUS_CHECK_TIMEOUT,
        help='Maximum wait time before the remote replication pair status '
        'changes to the expected status'),
    cfg.IntOpt(
        'hitachi_path_group_id',
        default=0, min=0, max=255,
        help='Path group ID assigned to the remote connection for remote '
        'replication'),
    cfg.IntOpt(
        'hitachi_quorum_disk_id',
        min=0, max=31,
        help='ID of the Quorum disk used for global-active device'),
    cfg.IntOpt(
        'hitachi_replication_copy_speed',
        min=1, max=15, default=3,
        help='Remote copy speed of storage system. 1 or 2 indicates '
             'low speed, 3 indicates middle speed, and a value between 4 and '
             '15 indicates high speed.'),
    cfg.BoolOpt(
        'hitachi_set_mirror_reserve_attribute',
        default=True,
        help='Whether or not to set the mirror reserve attribute'),
    cfg.IntOpt(
        'hitachi_replication_number',
        default=0, min=0, max=255,
        help='Instance number for REST API'),
]

COMMON_MIRROR_OPTS = [
    cfg.StrOpt(
        'hitachi_mirror_storage_id',
        default=None,
        help='ID of secondary storage system'),
    cfg.StrOpt(
        'hitachi_mirror_pool',
        default=None,
        help='Pool of secondary storage system'),
    cfg.StrOpt(
        'hitachi_mirror_snap_pool',
        default=None,
        help='Thin pool of secondary storage system'),
    cfg.StrOpt(
        'hitachi_mirror_ldev_range',
        default=None,
        help='Logical device range of secondary storage system'),
    cfg.ListOpt(
        'hitachi_mirror_target_ports',
        default=[],
        help='Target port names for host group or iSCSI target'),
    cfg.ListOpt(
        'hitachi_mirror_compute_target_ports',
        default=[],
        help=(
            'Target port names of compute node '
            'for host group or iSCSI target')),
    cfg.IntOpt(
        'hitachi_mirror_pair_target_number',
        min=0, max=99, default=0,
        help='Pair target name of the host group or iSCSI target'),
]

ISCSI_MIRROR_OPTS = [
    cfg.BoolOpt(
        'hitachi_mirror_use_chap_auth',
        default=False,
        help='Whether or not to use iSCSI authentication'),
    cfg.StrOpt(
        'hitachi_mirror_auth_user',
        default=None,
        help='iSCSI authentication username'),
    cfg.StrOpt(
        'hitachi_mirror_auth_password',
        default=None,
        secret=True,
        help='iSCSI authentication password'),
]

REST_MIRROR_OPTS = [
    cfg.ListOpt(
        'hitachi_mirror_rest_pair_target_ports',
        default=[],
        help='Target port names for pair of the host group or iSCSI target'),
]

REST_MIRROR_API_OPTS = [
    cfg.StrOpt(
        'hitachi_mirror_rest_user',
        default=None,
        help='Username of secondary storage system for REST API'),
    cfg.StrOpt(
        'hitachi_mirror_rest_password',
        default=None,
        secret=True,
        help='Password of secondary storage system for REST API'),
    cfg.StrOpt(
        'hitachi_mirror_rest_api_ip',
        default=None,
        help='IP address of REST API server'),
    cfg.PortOpt(
        'hitachi_mirror_rest_api_port',
        default=443,
        help='Port number of REST API server'),
]

REST_MIRROR_SSL_OPTS = [
    cfg.BoolOpt('hitachi_mirror_ssl_cert_verify',
                default=False,
                help='If set to True the http client will validate the SSL '
                     'certificate of the backend endpoint.'),
    cfg.StrOpt('hitachi_mirror_ssl_cert_path',
               help='Can be used to specify a non default path to a '
               'CA_BUNDLE file or directory with certificates of '
               'trusted CAs, which will be used to validate the backend'),
]

CONF = cfg.CONF
CONF.register_opts(_REP_OPTS)
CONF.register_opts(COMMON_MIRROR_OPTS)
CONF.register_opts(ISCSI_MIRROR_OPTS)
CONF.register_opts(REST_MIRROR_OPTS)
CONF.register_opts(REST_MIRROR_API_OPTS)
CONF.register_opts(REST_MIRROR_SSL_OPTS)

LOG = logging.getLogger(__name__)

MSG = utils.HBSDMsg


def _pack_rep_provider_location(pldev=None, sldev=None, rep_type=None):
    provider_location = {}
    if pldev is not None:
        provider_location['pldev'] = pldev
    if sldev is not None:
        provider_location['sldev'] = sldev
    if rep_type is not None:
        provider_location['remote-copy'] = rep_type
    return json.dumps(provider_location)


def _delays(short_interval, long_interval, timeout):
    start_time = timeutils.utcnow()
    watch = timeutils.StopWatch()
    i = 0
    while True:
        watch.restart()
        yield i
        if utils.timed_out(start_time, timeout):
            raise StopIteration()
        watch.stop()
        interval = long_interval if utils.timed_out(
            start_time, long_interval) else short_interval
        idle = max(interval - watch.elapsed(), 0)
        greenthread.sleep(idle)
        i += 1


class HBSDREPLICATION(rest.HBSDREST):

    def __init__(self, conf, driverinfo, db):
        super(HBSDREPLICATION, self).__init__(conf, driverinfo, db)
        conf.append_config_values(_REP_OPTS)
        if driverinfo['proto'] == 'iSCSI':
            conf.append_config_values(ISCSI_MIRROR_OPTS)
        conf.append_config_values(REST_MIRROR_OPTS)
        conf.append_config_values(REST_MIRROR_API_OPTS)
        conf.append_config_values(REST_MIRROR_SSL_OPTS)
        driver_impl_class = self.driver_info['driver_impl_class']
        self.primary = driver_impl_class(conf, driverinfo, db)
        self.rep_primary = self.primary
        self.rep_primary.is_primary = True
        self.rep_primary.storage_id = conf.safe_get(
            self.driver_info['param_prefix'] + '_storage_id') or ''
        self.primary_storage_id = self.rep_primary.storage_id
        self.secondary = driver_impl_class(conf, driverinfo, db)
        self.rep_secondary = self.secondary
        self.rep_secondary.is_secondary = True
        self.rep_secondary.storage_id = (
            conf.safe_get(
                self.driver_info['param_prefix'] + '_mirror_storage_id') or '')
        self.secondary_storage_id = self.rep_secondary.storage_id
        self.instances = self.rep_primary, self.rep_secondary
        self._LDEV_NAME = self.driver_info['driver_prefix'] + '-LDEV-%d-%d'

    def update_mirror_conf(self, conf, opts):
        for opt in opts:
            name = opt.name.replace('hitachi_mirror_', 'hitachi_')
            try:
                if opt.name == 'hitachi_mirror_pool':
                    if conf.safe_get('hitachi_mirror_pool'):
                        name = 'hitachi_pools'
                        value = [getattr(conf, opt.name)]
                    else:
                        raise ValueError()
                else:
                    value = getattr(conf, opt.name)
                setattr(conf, name, value)
            except Exception:
                with excutils.save_and_reraise_exception():
                    self.rep_secondary.output_log(
                        MSG.INVALID_PARAMETER, param=opt.name)

    def _replace_with_mirror_conf(self):
        conf = self.conf
        new_conf = utils.Config(conf)
        self.rep_secondary.conf = new_conf
        self.update_mirror_conf(new_conf, COMMON_MIRROR_OPTS)
        self.update_mirror_conf(new_conf, REST_MIRROR_OPTS)
        if self.rep_secondary.driver_info['volume_type'] == 'iscsi':
            self.update_mirror_conf(new_conf, ISCSI_MIRROR_OPTS)
        new_conf.san_login = (
            conf.safe_get(self.driver_info['param_prefix'] +
                          '_mirror_rest_user'))
        new_conf.san_password = (
            conf.safe_get(self.driver_info['param_prefix'] +
                          '_mirror_rest_password'))
        new_conf.san_ip = (
            conf.safe_get(self.driver_info['param_prefix'] +
                          '_mirror_rest_api_ip'))
        new_conf.san_api_port = (
            conf.safe_get(self.driver_info['param_prefix'] +
                          '_mirror_rest_api_port'))
        new_conf.driver_ssl_cert_verify = (
            conf.safe_get(self.driver_info['param_prefix'] +
                          '_mirror_ssl_cert_verify'))
        new_conf.driver_ssl_cert_path = (
            conf.safe_get(self.driver_info['param_prefix'] +
                          '_mirror_ssl_cert_path'))

    def do_setup(self, context):
        """Prepare for the startup of the driver."""
        self.rep_primary = self.primary
        self.rep_secondary = self.secondary
        self.ctxt = context
        try:
            self.rep_primary.do_setup(context)
            self.client = self.rep_primary.client
        except Exception:
            self.rep_primary.output_log(
                MSG.SITE_INITIALIZATION_FAILED, site='primary')
            self.rep_primary = None
        try:
            self._replace_with_mirror_conf()
            self.rep_secondary.do_setup(context)
        except Exception:
            self.rep_secondary.output_log(
                MSG.SITE_INITIALIZATION_FAILED, site='secondary')
            if not self.rep_primary:
                raise
            self.rep_secondary = None

    def update_volume_stats(self):
        """Update properties, capabilities and current states of the driver."""
        if self.rep_primary:
            data = self.rep_primary.update_volume_stats()
        else:
            data = self.rep_secondary.update_volume_stats()
        return data

    def _require_rep_primary(self):
        if not self.rep_primary:
            msg = utils.output_log(
                MSG.SITE_NOT_INITIALIZED, storage_id=self.primary_storage_id,
                site='primary')
            self.raise_error(msg)

    def _require_rep_secondary(self):
        if not self.rep_secondary:
            msg = utils.output_log(
                MSG.SITE_NOT_INITIALIZED, storage_id=self.secondary_storage_id,
                site='secondary')
            self.raise_error(msg)

    def _is_mirror_spec(self, extra_specs):
        topology = None
        if not extra_specs:
            return False
        if self.driver_info.get('driver_dir_name'):
            topology = extra_specs.get(
                self.driver_info['driver_dir_name'] + ':topology')
        if topology is None:
            return False
        elif topology == 'active_active_mirror_volume':
            return True
        else:
            msg = self.rep_primary.output_log(
                MSG.INVALID_EXTRA_SPEC_KEY,
                key=self.driver_info['driver_dir_name'] + ':topology',
                value=topology)
            self.raise_error(msg)

    def _create_rep_ldev(self, volume, extra_specs, rep_type, pvol=None):
        """Create a primary volume and  a secondary volume."""
        pool_id = self.rep_secondary.storage_info['pool_id'][0]
        ldev_range = self.rep_secondary.storage_info['ldev_range']
        qos_specs = utils.get_qos_specs_from_volume(volume)
        thread = greenthread.spawn(
            self.rep_secondary.create_ldev, volume.size, extra_specs,
            pool_id, ldev_range, qos_specs=qos_specs)
        if pvol is None:
            try:
                pool_id = self.rep_primary.get_pool_id_of_volume(volume)
                ldev_range = self.rep_primary.storage_info['ldev_range']
                pvol = self.rep_primary.create_ldev(volume.size,
                                                    extra_specs,
                                                    pool_id, ldev_range,
                                                    qos_specs=qos_specs)
            except exception.VolumeDriverException:
                self.rep_primary.output_log(MSG.CREATE_LDEV_FAILED)
        try:
            svol = thread.wait()
        except Exception:
            self.rep_secondary.output_log(MSG.CREATE_LDEV_FAILED)
            svol = None
        if pvol is None or svol is None:
            for vol, type_, instance in zip((pvol, svol), ('P-VOL', 'S-VOL'),
                                            self.instances):
                if vol is None:
                    msg = instance.output_log(
                        MSG.CREATE_REPLICATION_VOLUME_FAILED,
                        type=type_, rep_type=rep_type,
                        volume_id=volume.id,
                        volume_type=volume.volume_type.name, size=volume.size)
                else:
                    instance.delete_ldev(vol)
            self.raise_error(msg)
        thread = greenthread.spawn(
            self.rep_secondary.modify_ldev_name,
            svol, volume['id'].replace("-", ""))
        try:
            self.rep_primary.modify_ldev_name(
                pvol, volume['id'].replace("-", ""))
        finally:
            thread.wait()
        return pvol, svol

    def _create_rep_copy_group_name(self, ldev):
        return self.driver_info['target_prefix'] + '%s%02XU%02d' % (
            CONF.my_ip, self.conf.hitachi_replication_number, ldev >> 10)

    def _get_rep_copy_speed(self):
        rep_copy_speed = self.rep_primary.conf.safe_get(
            self.driver_info['param_prefix'] + '_replication_copy_speed')
        if rep_copy_speed:
            return rep_copy_speed
        else:
            return self.rep_primary.conf.hitachi_copy_speed

    def _get_wait_pair_status_change_params(self, wait_type):
        """Get a replication pair status information."""
        _wait_pair_status_change_params = {
            _WAIT_PAIR: {
                'instance': self.rep_primary,
                'remote_client': self.rep_secondary.client,
                'is_secondary': False,
                'transitional_status': ['COPY'],
                'expected_status': ['PAIR', 'PFUL'],
                'msgid': MSG.CREATE_REPLICATION_PAIR_FAILED,
                'status_keys': ['pvolStatus', 'svolStatus'],
            },
            _WAIT_PSUS: {
                'instance': self.rep_primary,
                'remote_client': self.rep_secondary.client,
                'is_secondary': False,
                'transitional_status': ['PAIR', 'PFUL'],
                'expected_status': ['PSUS', 'SSUS'],
                'msgid': MSG.SPLIT_REPLICATION_PAIR_FAILED,
                'status_keys': ['pvolStatus', 'svolStatus'],
            }
        }
        return _wait_pair_status_change_params[wait_type]

    def _wait_pair_status_change(self, copy_group_name, pvol, svol,
                                 rep_type, wait_type):
        """Wait until the replication pair status changes to the specified

        status.
        """
        for _ in _delays(
                self.conf.hitachi_replication_status_check_short_interval,
                self.conf.hitachi_replication_status_check_long_interval,
                self.conf.hitachi_replication_status_check_timeout):
            params = self._get_wait_pair_status_change_params(wait_type)
            status = params['instance'].client.get_remote_copypair(
                params['remote_client'], copy_group_name, pvol, svol,
                is_secondary=params['is_secondary'])
            statuses = [status.get(status_key) for status_key in
                        params['status_keys']]
            unexpected_status_set = (set(statuses) -
                                     set(params['expected_status']))
            if not unexpected_status_set:
                break
            if unexpected_status_set.issubset(
                    set(params['transitional_status'])):
                continue
            msg = params['instance'].output_log(
                params['msgid'], rep_type=rep_type, pvol=pvol, svol=svol,
                copy_group=copy_group_name, status='/'.join(statuses))
            self.raise_error(msg)
        else:
            status = params['instance'].client.get_remote_copypair(
                params['remote_client'], copy_group_name, pvol, svol,
                is_secondary=params['is_secondary'])
            msg = params['instance'].output_log(
                MSG.PAIR_CHANGE_TIMEOUT,
                rep_type=rep_type, pvol=pvol, svol=svol,
                copy_group=copy_group_name, current_status='/'.join(statuses),
                expected_status=str(params['expected_status']),
                timeout=self.conf.hitachi_replication_status_check_timeout)
            self.raise_error(msg)

    def _create_rep_pair(self, volume, pvol, svol, rep_type,
                         do_initialcopy=True):
        """Create a replication pair."""
        copy_group_name = self._create_rep_copy_group_name(pvol)

        @utils.synchronized_on_copy_group()
        def inner(self, remote_client, copy_group_name, secondary_storage_id,
                  conf, copyPace, parent):
            is_new_copy_grp = True
            result = self.get_remote_copy_grps(remote_client)
            if result:
                for data in result:
                    if copy_group_name == data['copyGroupName']:
                        is_new_copy_grp = False
                        break
            body = {
                'copyGroupName': copy_group_name,
                'copyPairName': parent._LDEV_NAME % (pvol, svol),
                'replicationType': rep_type,
                'remoteStorageDeviceId': secondary_storage_id,
                'pvolLdevId': pvol,
                'svolLdevId': svol,
                'pathGroupId': conf.hitachi_path_group_id,
                'localDeviceGroupName': copy_group_name + 'P',
                'remoteDeviceGroupName': copy_group_name + 'S',
                'isNewGroupCreation': is_new_copy_grp,
                'doInitialCopy': do_initialcopy,
                'isDataReductionForceCopy': False
            }
            if rep_type == parent.driver_info['mirror_attr']:
                body['quorumDiskId'] = conf.hitachi_quorum_disk_id
                body['copyPace'] = copyPace
                if is_new_copy_grp:
                    body['muNumber'] = 0
            self.add_remote_copypair(remote_client, body)

        inner(
            self.rep_primary.client, self.rep_secondary.client,
            copy_group_name, self.rep_secondary.storage_id,
            self.rep_secondary.conf, self._get_rep_copy_speed(),
            self)
        self._wait_pair_status_change(
            copy_group_name, pvol, svol, rep_type, _WAIT_PAIR)

    def _create_rep_ldev_and_pair(
            self, volume, extra_specs, rep_type, pvol=None):
        """Create volume and Replication pair."""
        capacity_saving = None
        if self.driver_info.get('driver_dir_name'):
            capacity_saving = extra_specs.get(
                self.driver_info['driver_dir_name'] + ':capacity_saving')
        if capacity_saving == 'deduplication_compression':
            msg = self.output_log(
                MSG.DEDUPLICATION_IS_ENABLED,
                rep_type=rep_type, volume_id=volume.id,
                volume_type=volume.volume_type.name, size=volume.size)
            if pvol is not None:
                self.rep_primary.delete_ldev(pvol)
            self.raise_error(msg)
        svol = None
        pvol, svol = self._create_rep_ldev(volume, extra_specs, rep_type, pvol)
        try:
            thread = greenthread.spawn(
                self.rep_secondary.initialize_pair_connection, svol)
            try:
                self.rep_primary.initialize_pair_connection(pvol)
            finally:
                thread.wait()
            if self.rep_primary.conf.\
                    hitachi_set_mirror_reserve_attribute:
                self.rep_secondary.client.assign_virtual_ldevid(svol)
            self._create_rep_pair(volume, pvol, svol, rep_type)
        except Exception:
            with excutils.save_and_reraise_exception():
                if svol is not None:
                    self.rep_secondary.terminate_pair_connection(svol)
                    if self.rep_primary.conf.\
                            hitachi_set_mirror_reserve_attribute:
                        self.rep_secondary.client.unassign_virtual_ldevid(
                            svol)
                    self.rep_secondary.delete_ldev(svol)
                if pvol is not None:
                    self.rep_primary.terminate_pair_connection(pvol)
                    self.rep_primary.delete_ldev(pvol)
        return pvol, svol

    def create_volume(self, volume):
        """Create a volume from a volume or snapshot and return its properties.

        """
        self._require_rep_primary()
        extra_specs = self.rep_primary.get_volume_extra_specs(volume)
        if self._is_mirror_spec(extra_specs):
            self._require_rep_secondary()
            rep_type = self.driver_info['mirror_attr']
            pldev, sldev = self._create_rep_ldev_and_pair(
                volume, extra_specs, rep_type)
            provider_location = _pack_rep_provider_location(
                pldev, sldev, rep_type)
            return {
                'provider_location': provider_location
            }
        return self.rep_primary.create_volume(volume)

    def _has_rep_pair(self, ldev, ldev_info=None):
        """Return if the specified LDEV has a replication pair.

        :param int ldev: The LDEV ID
        :param dict ldev_info: LDEV info
        :return: True if the LDEV status is normal and the LDEV has a
        replication pair, False otherwise
        :rtype: bool
        """
        if ldev_info is None:
            ldev_info = self.rep_primary.get_ldev_info(
                ['status', 'attributes'], ldev)
        return (ldev_info['status'] == rest.NORMAL_STS and
                self.driver_info['mirror_attr'] in ldev_info['attributes'])

    def _get_rep_pair_info(self, pldev, ldev_info=None):
        """Return replication pair info.

        :param int pldev: The ID of the LDEV(P-VOL in case of a pair)
        :param dict ldev_info: LDEV info
        :return: replication pair info. An empty dict if the LDEV does not
        have a pair.
        :rtype: dict
        """
        pair_info = {}
        if not self._has_rep_pair(pldev, ldev_info):
            return pair_info
        self._require_rep_secondary()
        copy_group_name = self._create_rep_copy_group_name(pldev)
        pairs = self.rep_primary.client.get_remote_copy_grp(
            self.rep_secondary.client,
            copy_group_name).get('copyPairs', [])
        for pair in pairs:
            if (pair.get('replicationType') in
                    [self.driver_info['mirror_attr']] and
                    pair['pvolLdevId'] == pldev):
                break
        else:
            return pair_info
        pair_info['pvol'] = pldev
        pair_info['svol_info'] = [{
            'ldev': pair.get('svolLdevId'),
            'rep_type': pair.get('replicationType'),
            'is_psus': pair.get('svolStatus') in ['SSUS', 'PFUS'],
            'pvol_status': pair.get('pvolStatus'),
            'svol_status': pair.get('svolStatus')}]
        return pair_info

    def _split_rep_pair(self, pvol, svol):
        copy_group_name = self._create_rep_copy_group_name(pvol)
        rep_type = self.driver_info['mirror_attr']
        self.rep_primary.client.split_remote_copypair(
            self.rep_secondary.client, copy_group_name, pvol, svol, rep_type)
        self._wait_pair_status_change(
            copy_group_name, pvol, svol, rep_type, _WAIT_PSUS)

    def _delete_rep_pair(self, pvol, svol):
        """Delete a replication pair."""
        copy_group_name = self._create_rep_copy_group_name(pvol)
        self._split_rep_pair(pvol, svol)
        self.rep_primary.client.delete_remote_copypair(
            self.rep_secondary.client, copy_group_name, pvol, svol)

    def _delete_volume_pre_check(self, volume):
        """Pre-check for delete_volume().

        :param Volume volume: The volume to be checked
        :return: svol: The ID of the S-VOL
        :rtype: int
        :return: pvol_is_invalid: True if P-VOL is invalid, False otherwise
        :rtype: bool
        :return: svol_is_invalid: True if S-VOL is invalid, False otherwise
        :rtype: bool
        :return: pair_exists: True if the pair exists, False otherwise
        :rtype: bool
        """
        # Check if the LDEV in the primary storage corresponds to the volume
        pvol_is_invalid = True
        # To avoid KeyError when accessing a missing attribute, set the default
        # value to None.
        pvol_info = defaultdict(lambda: None)
        pvol = self.rep_primary.get_ldev(volume)
        if pvol is not None:
            if self.rep_primary.is_invalid_ldev(pvol, volume, pvol_info):
                # If the LDEV is assigned to another object, skip deleting it.
                self.rep_primary.output_log(
                    MSG.SKIP_DELETING_LDEV, obj='volume', obj_id=volume.id,
                    ldev=pvol, ldev_label=pvol_info['label'])
            else:
                pvol_is_invalid = False
        # Check if the pair exists on the storage.
        pair_exists = False
        svol_is_invalid = True
        svol = None
        if not pvol_is_invalid:
            pair_info = self._get_rep_pair_info(pvol, pvol_info)
            if pair_info:
                pair_exists = True
                # Because this pair is a valid P-VOL's pair, we need to delete
                # it and its LDEVs. The LDEV ID of the S-VOL to be deleted is
                # uniquely determined from the pair info. Therefore, there is
                # no need to get it from provider_location or to validate the
                # S-VOL by comparing the volume ID with the S-VOL's label.
                svol = pair_info['svol_info'][0]['ldev']
                svol_is_invalid = False
        # Check if the LDEV in the secondary storage corresponds to the volume
        if svol_is_invalid:
            svol = self.rep_secondary.get_ldev(volume)
            if svol is not None:
                # To avoid KeyError when accessing a missing attribute, set the
                # default value to None.
                svol_info = defaultdict(lambda: None)
                if self.rep_secondary.is_invalid_ldev(svol, volume, svol_info):
                    # If the LDEV is assigned to another object, skip deleting
                    # it.
                    self.rep_secondary.output_log(
                        MSG.SKIP_DELETING_LDEV, obj='volume', obj_id=volume.id,
                        ldev=svol, ldev_label=svol_info['label'])
                else:
                    svol_is_invalid = False
        return svol, pvol_is_invalid, svol_is_invalid, pair_exists

    def delete_volume(self, volume):
        """Delete the specified volume."""
        self._require_rep_primary()
        ldev = self.rep_primary.get_ldev(volume)
        if ldev is None:
            self.rep_primary.output_log(
                MSG.INVALID_LDEV_FOR_DELETION, method='delete_volume',
                id=volume.id)
            return
        # Run pre-check.
        svol, pvol_is_invalid, svol_is_invalid, pair_exists = (
            self._delete_volume_pre_check(volume))
        # Delete the pair if it exists.
        if pair_exists:
            self._delete_rep_pair(ldev, svol)
        # Delete LDEVs if they are valid.
        thread = None
        if not svol_is_invalid:
            thread = greenthread.spawn(
                self.rep_secondary.delete_volume, volume)
        try:
            if not pvol_is_invalid:
                self.rep_primary.delete_volume(volume)
        finally:
            if thread is not None:
                thread.wait()

    def delete_ldev(self, ldev, ldev_info=None):
        """Delete the specified LDEV[s].

        :param int ldev: The ID of the LDEV(P-VOL in case of a pair) to be
        deleted
        :param dict ldev_info: LDEV(P-VOL in case of a pair) info
        :return: None
        """
        self._require_rep_primary()
        pair_info = self._get_rep_pair_info(ldev, ldev_info)
        if pair_info:
            self._delete_rep_pair(ldev, pair_info['svol_info'][0]['ldev'])
            th = greenthread.spawn(self.rep_secondary.delete_ldev,
                                   pair_info['svol_info'][0]['ldev'])
            try:
                self.rep_primary.delete_ldev(ldev)
            finally:
                th.wait()
        else:
            self.rep_primary.delete_ldev(ldev)

    def _create_rep_volume_from_src(
            self, volume, extra_specs, src, src_type, operation):
        """Create a replication volume from a volume or snapshot and return

        its properties.
        """
        rep_type = self.driver_info['mirror_attr']
        data = self.rep_primary.create_volume_from_src(
            volume, src, src_type, is_rep=True)
        new_ldev = self.rep_primary.get_ldev(data)
        sldev = self._create_rep_ldev_and_pair(
            volume, extra_specs, rep_type, new_ldev)[1]
        provider_location = _pack_rep_provider_location(
            new_ldev, sldev, rep_type)
        return {
            'provider_location': provider_location,
        }

    def _create_volume_from_src(self, volume, src, src_type):
        """Create a volume from a volume or snapshot and return its properties.

        """
        self._require_rep_primary()
        operation = ('create a volume from a %s' % src_type)
        extra_specs = self.rep_primary.get_volume_extra_specs(volume)
        if self._is_mirror_spec(extra_specs):
            self._require_rep_secondary()
            return self._create_rep_volume_from_src(
                volume, extra_specs, src, src_type, operation)
        return self.rep_primary.create_volume_from_src(volume, src, src_type)

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume and return its properties."""
        return self._create_volume_from_src(
            volume, src_vref, common.STR_VOLUME)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot and return its properties."""
        return self._create_volume_from_src(
            volume, snapshot, common.STR_SNAPSHOT)

    def create_snapshot(self, snapshot):
        """Create a snapshot from a volume and return its properties."""
        self._require_rep_primary()
        return self.rep_primary.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Delete the specified snapshot."""
        self._require_rep_primary()
        self.rep_primary.delete_snapshot(snapshot)

    def _get_remote_copy_mode(self, vol):
        provider_location = vol.get('provider_location')
        if not provider_location:
            return None
        if provider_location.startswith('{'):
            loc = json.loads(provider_location)
            if isinstance(loc, dict):
                return loc.get('remote-copy')
        return None

    def _merge_properties(self, prop1, prop2):
        if prop1 is None:
            if prop2 is None:
                return []
            return prop2
        elif prop2 is None:
            return prop1
        d = dict(prop1)
        for key in ('target_luns', 'target_wwn', 'target_portals',
                    'target_iqns'):
            if key in d:
                d[key] = d[key] + prop2[key]
        if 'initiator_target_map' in d:
            for key2 in d['initiator_target_map']:
                d['initiator_target_map'][key2] = (
                    d['initiator_target_map'][key2]
                    + prop2['initiator_target_map'][key2])
        return d

    def initialize_connection_mirror(self, volume, connector):
        lun = None
        prop1 = None
        prop2 = None
        if self.rep_primary:
            try:
                conn_info1 = (
                    self.rep_primary.initialize_connection(
                        volume, connector, is_mirror=True))
            except Exception as ex:
                self.rep_primary.output_log(
                    MSG.REPLICATION_VOLUME_OPERATION_FAILED,
                    operation='attach', type='P-VOL',
                    volume_id=volume.id, reason=str(ex))
            else:
                prop1 = conn_info1['data']
                if self.driver_info['volume_type'] == 'fibre_channel':
                    if 'target_lun' in prop1:
                        lun = prop1['target_lun']
                    else:
                        lun = prop1['target_luns'][0]
        if self.rep_secondary:
            try:
                conn_info2 = (
                    self.rep_secondary.initialize_connection(
                        volume, connector, lun=lun, is_mirror=True))
            except Exception as ex:
                self.rep_secondary.output_log(
                    MSG.REPLICATION_VOLUME_OPERATION_FAILED,
                    operation='attach', type='S-VOL',
                    volume_id=volume.id, reason=str(ex))
                if prop1 is None:
                    raise ex
            else:
                prop2 = conn_info2['data']
        conn_info = {
            'driver_volume_type': self.driver_info['volume_type'],
            'data': self._merge_properties(prop1, prop2),
        }
        return conn_info

    def initialize_connection(self, volume, connector, is_snapshot=False):
        """Initialize connection between the server and the volume."""
        if (self._get_remote_copy_mode(volume) ==
                self.driver_info['mirror_attr']):
            conn_info = self.initialize_connection_mirror(volume, connector)
            if self.driver_info['volume_type'] == 'fibre_channel':
                fczm_utils.add_fc_zone(conn_info)
            return conn_info
        else:
            self._require_rep_primary()
            return self.rep_primary.initialize_connection(
                volume, connector, is_snapshot)

    def terminate_connection_mirror(self, volume, connector):
        prop1 = None
        prop2 = None
        if self.rep_primary:
            try:
                conn_info1 = self.rep_primary.terminate_connection(
                    volume, connector, is_mirror=True)
            except Exception as ex:
                self.rep_primary.output_log(
                    MSG.REPLICATION_VOLUME_OPERATION_FAILED,
                    operation='detach', type='P-VOL',
                    volume_id=volume.id, reason=str(ex))
                raise ex
            else:
                if conn_info1:
                    prop1 = conn_info1['data']
        if self.rep_secondary:
            try:
                conn_info2 = self.rep_secondary.terminate_connection(
                    volume, connector, is_mirror=True)
            except Exception as ex:
                self.rep_secondary.output_log(
                    MSG.REPLICATION_VOLUME_OPERATION_FAILED,
                    operation='detach', type='S-VOL',
                    volume_id=volume.id, reason=str(ex))
                raise ex
            else:
                if conn_info2:
                    prop2 = conn_info2['data']
        conn_info = {
            'driver_volume_type': self.driver_info['volume_type'],
            'data': self._merge_properties(prop1, prop2),
        }
        return conn_info

    def terminate_connection(self, volume, connector):
        """Terminate connection between the server and the volume."""
        if (self._get_remote_copy_mode(volume) ==
                self.driver_info['mirror_attr']):
            conn_info = self.terminate_connection_mirror(volume, connector)
            if self.driver_info['volume_type'] == 'fibre_channel':
                fczm_utils.remove_fc_zone(conn_info)
            return conn_info
        else:
            self._require_rep_primary()
            return self.rep_primary.terminate_connection(volume, connector)

    def _extend_pair_volume(self, volume, new_size, ldev, pair_info):
        """Extend the specified  replication volume to the specified size."""
        rep_type = self.driver_info['mirror_attr']
        pvol_info = self.rep_primary.get_ldev_info(
            ['numOfPorts'], pair_info['pvol'])
        if pvol_info['numOfPorts'] > 1:
            msg = self.rep_primary.output_log(
                MSG.EXTEND_REPLICATION_VOLUME_ERROR,
                rep_type=rep_type, volume_id=volume.id, ldev=ldev,
                source_size=volume.size, destination_size=new_size,
                pvol=pair_info['pvol'], svol='',
                pvol_num_of_ports=pvol_info['numOfPorts'],
                svol_num_of_ports='')
            self.raise_error(msg)
        self._delete_rep_pair(
            ldev, pair_info['svol_info'][0]['ldev'])
        thread = greenthread.spawn(
            self.rep_secondary.extend_volume, volume, new_size)
        try:
            self.rep_primary.extend_volume(volume, new_size)
        finally:
            thread.wait()
        self._create_rep_pair(
            volume, pair_info['pvol'], pair_info['svol_info'][0]['ldev'],
            rep_type, do_initialcopy=False)

    def extend_volume(self, volume, new_size):
        """Extend the specified volume to the specified size."""
        self._require_rep_primary()
        ldev = self.rep_primary.get_ldev(volume)
        if ldev is None:
            msg = self.rep_primary.output_log(
                MSG.INVALID_LDEV_FOR_EXTENSION, volume_id=volume.id)
            self.raise_error(msg)
        pair_info = self._get_rep_pair_info(ldev)
        if pair_info:
            self._extend_pair_volume(volume, new_size, ldev, pair_info)
        else:
            self.rep_primary.extend_volume(volume, new_size)

    def manage_existing(self, volume, existing_ref):
        """Return volume properties which Cinder needs to manage the volume."""
        self._require_rep_primary()
        return self.rep_primary.manage_existing(volume, existing_ref)

    def manage_existing_get_size(self, volume, existing_ref):
        """Return the size[GB] of the specified volume."""
        self._require_rep_primary()
        return self.rep_primary.manage_existing_get_size(volume, existing_ref)

    def unmanage(self, volume):
        """Prepare the volume for removing it from Cinder management."""
        self._require_rep_primary()
        ldev = self.rep_primary.get_ldev(volume)
        if ldev is None:
            self.rep_primary.output_log(
                MSG.INVALID_LDEV_FOR_DELETION,
                method='unmanage', id=volume.id)
            return
        if self._has_rep_pair(ldev):
            msg = self.rep_primary.output_log(
                MSG.REPLICATION_PAIR_ERROR,
                operation='unmanage a volume', volume=volume.id,
                snapshot_info='', ldev=ldev)
            self.raise_error(msg)
        self.rep_primary.unmanage(volume)

    def discard_zero_page(self, volume):
        self._require_rep_primary()
        ldev = self.rep_primary.get_ldev(volume)
        if self._has_rep_pair(ldev):
            self._require_rep_secondary()
            th = greenthread.spawn(
                self.rep_secondary.discard_zero_page, volume)
            try:
                self.rep_primary.discard_zero_page(volume)
            finally:
                th.wait()
        else:
            self.rep_primary.discard_zero_page(volume)

    def unmanage_snapshot(self, snapshot):
        if not self.rep_primary:
            return self.rep_secondary.unmanage_snapshot(snapshot)
        else:
            return self.rep_primary.unmanage_snapshot(snapshot)

    def retype(self, ctxt, volume, new_type, diff, host):
        self._require_rep_primary()
        ldev = self.rep_primary.get_ldev(volume)
        if ldev is None:
            msg = self.rep_primary.output_log(
                MSG.INVALID_LDEV_FOR_VOLUME_COPY,
                type='volume', id=volume.id)
            self.raise_error(msg)
        if (self._has_rep_pair(ldev) or
                self._is_mirror_spec(new_type['extra_specs'])):
            return False
        return self.rep_primary.retype(
            ctxt, volume, new_type, diff, host)

    def migrate_volume(self, volume, host):
        self._require_rep_primary()
        ldev = self.rep_primary.get_ldev(volume)
        if ldev is None:
            msg = self.rep_primary.output_log(
                MSG.INVALID_LDEV_FOR_VOLUME_COPY,
                type='volume', id=volume.id)
            self.raise_error(msg)
        if self._get_rep_pair_info(ldev):
            return False, None
        else:
            return self.rep_primary.migrate_volume(volume, host)

    def _resync_rep_pair(self, pvol, svol):
        copy_group_name = self._create_rep_copy_group_name(pvol)
        rep_type = self.driver_info['mirror_attr']
        self.rep_primary.client.resync_remote_copypair(
            self.rep_secondary.client, copy_group_name, pvol, svol,
            rep_type, copy_speed=self._get_rep_copy_speed())
        self._wait_pair_status_change(
            copy_group_name, pvol, svol, rep_type, _WAIT_PAIR)

    def revert_to_snapshot(self, volume, snapshot):
        """Rollback the specified snapshot."""
        self._require_rep_primary()
        ldev = self.rep_primary.get_ldev(volume)
        svol = self.rep_primary.get_ldev(snapshot)
        if None in (ldev, svol):
            raise NotImplementedError()
        pair_info = self._get_rep_pair_info(ldev)
        is_snap = self.rep_primary.has_snap_pair(ldev, svol)
        if pair_info and is_snap:
            self._split_rep_pair(pair_info['pvol'],
                                 pair_info['svol_info'][0]['ldev'])
        try:
            self.rep_primary.revert_to_snapshot(volume, snapshot)
        finally:
            if pair_info and is_snap:
                self._resync_rep_pair(pair_info['pvol'],
                                      pair_info['svol_info'][0]['ldev'])

    def create_group(self):
        self._require_rep_primary()
        return self.rep_primary.create_group()

    def delete_group(self, group, volumes):
        self._require_rep_primary()
        return super(HBSDREPLICATION, self).delete_group(group, volumes)

    def create_group_from_src(
            self, context, group, volumes, snapshots=None, source_vols=None):
        self._require_rep_primary()
        return super(HBSDREPLICATION, self).create_group_from_src(
            context, group, volumes, snapshots, source_vols)

    def update_group(self, group, add_volumes=None):
        self._require_rep_primary()
        return self.rep_primary.update_group(group, add_volumes)

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        self._require_rep_primary()
        return self.rep_primary.create_group_snapshot(
            context, group_snapshot, snapshots)

    def delete_group_snapshot(self, group_snapshot, snapshots):
        self._require_rep_primary()
        return self.rep_primary.delete_group_snapshot(
            group_snapshot, snapshots)
