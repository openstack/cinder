# Copyright (C) 2025, Hitachi, Ltd.
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
from cinder.objects import fields
from cinder.objects import volume as cinder_volume
from cinder.volume.drivers.hitachi import hbsd_common as common
from cinder.volume.drivers.hitachi import hbsd_rest as rest
from cinder.volume.drivers.hitachi import hbsd_utils as utils
from cinder.volume import manager
from cinder.zonemanager import utils as fczm_utils

_ASYNC_STRING = 'async'

_REP_STATUS_CHECK_SHORT_INTERVAL = 5
_REP_STATUS_CHECK_LONG_INTERVAL = 10 * 60
_REP_STATUS_CHECK_TIMEOUT = 24 * 60 * 60

_PRIMARY = 1
_SECONDARY = 2
_PRIMARY_SECONDARY = 3

_WAIT_PAIR = 1
_WAIT_PSUS = 2
_WAIT_SSWS = 3
_WAIT_SPLIT = 4

_REP_FAILBACK = manager.VolumeManager.FAILBACK_SENTINEL

_JOURNAL_VOLUME_LABEL = '%s-JNL'

_MIRROR_IDENTIFIER = 'G'
_ASYNC_IDENTIFIER = 'U'

_INHERITED_REP_VOLUME_OPTS = [
    'replication_device',
]

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

COMMON_REPLICATION_OPTS = [
    cfg.IntOpt(
        'hitachi_replication_mun',
        default=1, min=0, max=3,
        help='Mirror unit ID used for asynchronous remote replication'),
    cfg.IntOpt(
        'hitachi_replication_journal_size',
        default=None, min=10, max=1024,
        help='Size in gigabytes of the journal used for asynchronous remote '
        'replication'),
    cfg.IntOpt(
        'hitachi_replication_journal_overflow_tolerance',
        default=60, min=0, max=600,
        help='Delay in seconds before a volume pair is split after the data '
        'in a journal volume reaches its maximum'),
    cfg.BoolOpt(
        'hitachi_replication_journal_use_cache',
        default=True,
        help='Whether or not to cache restore journal data in asynchronous '
        'remote replication'),
    cfg.StrOpt(
        'hitachi_replication_journal_transfer_speed',
        default='256',
        choices=['3', '10', '100', '256'],
        help='Site-to-site journal data transfer speed in megabits per second '
        'in asynchronous remote replication'),
    cfg.StrOpt(
        'hitachi_replication_journal_creation_speed',
        default='L',
        choices=['L', 'M', 'H'],
        help='Journal data creation speed for initial copy in asynchronous '
        'remote replication'),
    cfg.IntOpt(
        'hitachi_replication_journal_path_failure_tolerance',
        default=5, min=0, max=60,
        help='Delay in minutes before a volume pair is split after path '
        'failure occurs'),
]

_REPLICATION_DEVICE_KEY_NAMES = [
    'storage_id',
    'pool',
    'snap_pool',
    'ldev_range',
    'target_ports',
    'compute_target_ports',
    'pair_target_number',
    'rest_pair_target_ports',
]

_REPLICATION_DEVICE_ISCSI_KEY_NAMES = [
    'use_chap_auth',
    'chap_username',
    'chap_password',
]

_REPLICATION_DEVICE_STANDARD_KEY_NAMES = [
    'driver_ssl_cert_verify',
    'driver_ssl_cert_path',
    'san_login',
    'san_password',
    'san_ip',
    'san_api_port',
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

_MSGID_JOURNAL_ID_ALREADY_USED = 'KART40054-E'
_MSGID_NO_AVAILABLE_JOURNAL_ID = 'KART40046-E'
_MSGID_INSTANCE_CANNOT_OPERATED = 'KART40041-E'

_MAX_JID_COUNT_EXCEEDED = ('2E23', '5000')

CONF = cfg.CONF
CONF.register_opts(_REP_OPTS)
CONF.register_opts(COMMON_REPLICATION_OPTS)
CONF.register_opts(COMMON_MIRROR_OPTS)
CONF.register_opts(ISCSI_MIRROR_OPTS)
CONF.register_opts(REST_MIRROR_OPTS)
CONF.register_opts(REST_MIRROR_API_OPTS)
CONF.register_opts(REST_MIRROR_SSL_OPTS)

LOG = logging.getLogger(__name__)

MSG = utils.HBSDMsg


def _check_rep_ldev(self, volume, operation):
    if (('group_id' in volume and volume.group_id) or
            ('consistencygroup_id' in volume and volume.consistencygroup_id)):
        group = (volume.group_id if 'group_id' in volume and
                 volume.group_id else volume.consistencygroup_id)
        msg = utils.output_log(
            MSG.REPLICATION_AND_GROUP_ERROR, operation=operation,
            volume=volume.id, group=group)
        self.raise_error(msg)


def _get_rep_type(self, extra_specs):
    replication_type = extra_specs.get('replication_type')
    if replication_type is not None:
        if len(replication_type.split()) == 2:
            replication_type = replication_type.split()[1]
        if replication_type == _ASYNC_STRING:
            return self.driver_info['rep_type_async']
        msg = utils.output_log(
            MSG.INVALID_EXTRA_SPEC_KEY, key='replication_type',
            value=replication_type)
        self.raise_error(msg)
    return self.driver_info['rep_type_async']


def _pack_rep_provider_location(pldev=None, sldev=None, rep_type=None):
    provider_location = {}
    if pldev is not None:
        provider_location['pldev'] = pldev
    if sldev is not None:
        provider_location['sldev'] = sldev
    if rep_type is not None:
        provider_location['remote-copy'] = rep_type
    return json.dumps(provider_location)


def _get_unused_minimum_value(value_list):
    value = 0
    while True:
        if value not in value_list:
            return value
        value += 1


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


def _get_ldev_site(obj):
    if not obj:
        return None
    provider_location = obj.get('provider_location')
    if not provider_location:
        return None
    if provider_location.isdigit():
        return _PRIMARY
    if provider_location.startswith('{'):
        loc = json.loads(provider_location)
        if isinstance(loc, dict):
            if 'sldev' in loc and 'pldev' not in loc:
                return _SECONDARY
            if 'pldev' in loc and 'sldev' not in loc:
                return _PRIMARY
            if 'pldev' in loc and 'sldev' in loc:
                return _PRIMARY_SECONDARY
    return None


def _get_failover_volume_update(volumes, failover_success_volumes):
    volume_updates = []
    for volume in volumes:
        volume_update = {'volume_id': volume.id}
        if volume in failover_success_volumes:
            volume_update['updates'] = {
                'replication_status': fields.ReplicationStatus.FAILED_OVER}
            for snapshot in volume.snapshots:
                if _get_ldev_site(snapshot) == _PRIMARY:
                    snapshot.status = fields.SnapshotStatus.ERROR
                    snapshot.save()
        else:
            volume_update['updates'] = {'status': 'error'}
            if volume.replication_status in (
                    fields.ReplicationStatus.ENABLED,
                    fields.ReplicationStatus.FAILOVER_ERROR):
                volume_update['updates']['replication_status'] = (
                    fields.ReplicationStatus.FAILOVER_ERROR)
        volume_updates.append(volume_update)
    return volume_updates


class HBSDREPLICATION(rest.HBSDREST):

    def __init__(self, conf, driverinfo, db, active_backend_id=None):
        super(HBSDREPLICATION, self).__init__(conf, driverinfo, db)
        conf.append_config_values(_REP_OPTS)
        conf.append_config_values(COMMON_REPLICATION_OPTS)
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
                self.driver_info['param_prefix'] + '_mirror_storage_id') or
            conf.safe_get('replication_device')[0].get('storage_id') or '')
        self.secondary_storage_id = self.rep_secondary.storage_id
        self._active_backend_id = active_backend_id
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
        new_conf = utils.Config(conf, {})
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
        if self.conf.hitachi_mirror_storage_id:
            self.rep_primary = self.primary
            self.rep_secondary = self.secondary
            self.ctxt = context
            try:
                self.rep_primary.check_opts(
                    self.rep_primary.conf, _REP_OPTS)
                self.rep_primary.do_setup(context)
                self.client = self.rep_primary.client
            except Exception:
                self.rep_primary.output_log(
                    MSG.SITE_INITIALIZATION_FAILED, site='primary')
                self.rep_primary = None
            try:
                self.rep_secondary.check_opts(
                    self.rep_secondary.conf, _REP_OPTS)
                self._replace_with_mirror_conf()
                self.rep_secondary.do_setup(context)
            except Exception:
                self.rep_secondary.output_log(
                    MSG.SITE_INITIALIZATION_FAILED, site='secondary')
                if not self.rep_primary:
                    raise
                self.rep_secondary = None
        else:
            self.ctxt = context
            self._check_param()
            self._setup_replication()
            if not self._active_backend_id:
                self.rep_primary.do_setup(context)
            self.rep_secondary.do_setup(context)

    def _check_param(self):
        """Check parameter values and consistency among them."""
        self.rep_primary.check_opt_value(
            self.rep_primary.conf, _INHERITED_REP_VOLUME_OPTS)
        self.rep_primary.check_opts(
            self.rep_primary.conf, _REP_OPTS)
        self.rep_primary.check_opts(
            self.rep_primary.conf, COMMON_REPLICATION_OPTS)
        if not self.conf.safe_get(
                self.driver_info['param_prefix'] +
                '_replication_journal_size'):
            msg = utils.output_log(
                MSG.INVALID_PARAMETER,
                param='hitachi_replication_journal_size')
            self.raise_error(msg)

    def _create_rep_conf(self, conf):
        opts = {}
        opt_list = self.driver_info['driver_class'].get_driver_options()
        for opt in opt_list:
            opts[opt.name] = opt
        return utils.Config(conf, opts)

    def _setup_replication(self):
        """Set up the replication device."""
        self.rep_secondary.conf = self._create_rep_conf(self.conf)

        rep_devs = self.conf.safe_get('replication_device')
        if len(rep_devs) > 1:
            msg = utils.output_log(
                MSG.DRIVER_INITIALIZE_FAILED,
                config_group=self.conf.config_group,
                param='replication_device')
            self.raise_error(msg)

        rep_dev = dict(rep_devs[0])
        if not rep_dev.get('backend_id'):
            msg = utils.output_log(
                MSG.INVALID_PARAMETER,
                param=('replication_device[backend_id]'))
            self.raise_error(msg)
        self.rep_secondary.backend_id = rep_dev.pop('backend_id')

        names = (_REPLICATION_DEVICE_KEY_NAMES +
                 _REPLICATION_DEVICE_STANDARD_KEY_NAMES)
        if self.driver_info['volume_type'] == 'iscsi':
            names += _REPLICATION_DEVICE_ISCSI_KEY_NAMES
        for name in names:
            opt_prefix = ('hitachi_' if name not in
                          (_REPLICATION_DEVICE_STANDARD_KEY_NAMES +
                           _REPLICATION_DEVICE_ISCSI_KEY_NAMES) else '')
            opt_name = opt_prefix + name
            if opt_name == 'hitachi_pool':
                opt_name = 'hitachi_pools'
            opt_val = rep_dev.pop(name, None)
            try:
                self.rep_secondary.conf.update(opt_name, opt_val)
            except Exception:
                msg = utils.output_log(
                    MSG.INVALID_PARAMETER,
                    param=('replication_device[%s]' % name))
                self.raise_error(msg)

        if rep_dev:
            names = ', '.join(rep_dev.keys())
            msg = utils.output_log(
                MSG.INVALID_PARAMETER,
                param=('replication_device[%s]' % names))
            self.raise_error(msg)

        if len(getattr(self.rep_secondary.conf, 'hitachi_pools', [])) != 1:
            msg = utils.output_log(
                MSG.INVALID_PARAMETER,
                param=('replication_device[pool]'))
            self.raise_error(msg)

    def update_volume_stats(self):
        """Update properties, capabilities and current states of the driver."""
        if self.conf.hitachi_mirror_storage_id:
            if self.rep_primary:
                data = self.rep_primary.update_volume_stats()
            else:
                data = self.rep_secondary.update_volume_stats()
        else:
            data = self._get_active_backend().update_volume_stats()
            data['replication_enabled'] = True
            data['replication_targets'] = [self.rep_secondary.backend_id]
            data['replication_type'] = [_ASYNC_STRING]
            if 'pools' in data:
                for pool in data['pools']:
                    pool['replication_enabled'] = True
                    pool['replication_targets'] = [
                        self.rep_secondary.backend_id]
                    pool['replication_type'] = [_ASYNC_STRING]
                    pool['location_info']['execution_site'] = (
                        utils.SECONDARY_STR if self._active_backend_id else
                        utils.PRIMARY_STR)
        return data

    def _get_active_backend(self):
        """Get the active backend."""
        return (self.rep_secondary if self._active_backend_id else
                self.rep_primary)

    def _convert_model_update(self, model_update, is_snapshot=False):
        """Convert a model update information."""
        if self.conf.hitachi_mirror_storage_id:
            return model_update
        if not is_snapshot:
            model_update['replication_status'] = (
                fields.ReplicationStatus.DISABLED)
        if not self._active_backend_id:
            model_update['provider_location'] = (
                _pack_rep_provider_location(
                    pldev=int(model_update['provider_location'])))
        else:
            model_update['provider_location'] = (
                _pack_rep_provider_location(
                    sldev=int(model_update['provider_location'])))
        return model_update

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
        return self.driver_info['target_prefix'] + '%s%02X%s%02d' % (
            CONF.my_ip, self.conf.hitachi_replication_number,
            _MIRROR_IDENTIFIER if self.conf.hitachi_mirror_storage_id else
            _ASYNC_IDENTIFIER, ldev >> 10)

    def _modify_journal(self, instance, journal_id):
        """Modify the journal information."""
        tolerance = (
            self.conf.hitachi_replication_journal_path_failure_tolerance)
        body = {
            'dataOverflowWatchInSeconds':
                self.conf.hitachi_replication_journal_overflow_tolerance,
            'isCacheModeEnabled':
                self.conf.hitachi_replication_journal_use_cache,
            'copySpeed':
                int(self.conf.hitachi_replication_journal_transfer_speed),
            'mirrorUnit': {
                'muNumber': self.conf.hitachi_replication_mun,
                'copyPace':
                    self.conf.hitachi_replication_journal_creation_speed,
                'pathBlockadeWatchInMinutes': tolerance},
        }
        instance.client.modify_journal(journal_id, body)

    def _delete_journals(self, journal_ids):
        """Delete journal volumes."""
        for instance, journal_id in zip(self.instances, journal_ids):
            try:
                ldev = instance.client.get_journal(journal_id, no_log=True)[
                    'firstLdevId']
                instance.client.delete_journal(journal_id, no_log=True)
                instance.delete_ldev(ldev)
                LOG.debug(
                    'A journal and its LDEV were deleted. (storage: '
                    '%(storage)s, journal: %(journal)s, LDEV: %(ldev)s)',
                    {'storage': instance.storage_id[-6:],
                     'journal': journal_id, 'ldev': ldev})
            except exception.VolumeDriverException:
                LOG.debug(
                    'A journal and/or its LDEV were not deleted. '
                    '(storage: %(storage)s, journal: %(journal)s)',
                    {'storage': instance.storage_id[-6:],
                     'journal': journal_id})

    def create_journals(self, volume, copy_group_name):
        """Create a journal volume."""
        journal_ids = []
        journal_ldevs = []
        try:
            for instance in self.instances:
                pool_id = (self.rep_primary.get_pool_id_of_volume(volume)
                           if instance == self.rep_primary
                           else self.rep_secondary.storage_info['pool_id'][0])
                ldev_range = instance.storage_info['ldev_range']
                ldev = instance.create_ldev(
                    self.conf.hitachi_replication_journal_size, {},
                    pool_id, ldev_range)
                instance.client.modify_ldev(
                    ldev, {'label': _JOURNAL_VOLUME_LABEL % copy_group_name})
                journal_ldevs.append(ldev)
                while True:
                    journal_list = instance.client.get_journals()
                    journal_id = _get_unused_minimum_value(
                        [journal['journalId'] for journal in journal_list])
                    errobj = instance.client.add_journal(
                        journal_id, ldev, ignore_message_id=[
                            _MSGID_JOURNAL_ID_ALREADY_USED,
                            _MSGID_NO_AVAILABLE_JOURNAL_ID],
                        ignore_error=[_MAX_JID_COUNT_EXCEEDED])[1]
                    if (errobj.get('messageId') ==
                            _MSGID_JOURNAL_ID_ALREADY_USED):
                        continue
                    if (errobj.get('messageId') ==
                            _MSGID_NO_AVAILABLE_JOURNAL_ID or
                            utils.safe_get_err_code(errobj) ==
                            _MAX_JID_COUNT_EXCEEDED):
                        msg = instance.output_log(
                            MSG.CREATE_JOURNAL_FAILED, volume=volume.id)
                        self.raise_error(msg)
                    LOG.debug(
                        'A journal and its LDEV were created. (storage: '
                        '%(storage)s, journal: %(journal)s, LDEV: %(ldev)s)',
                        {'storage': instance.storage_id[-6:],
                         'journal': journal_id, 'ldev': ldev})
                    journal_ids.append(journal_id)
                    self._modify_journal(instance, journal_id)
                    break
        except exception.VolumeDriverException:
            with excutils.save_and_reraise_exception():
                self._delete_journals(journal_ids)
                if len(journal_ldevs) > len(journal_ids):
                    self.instances[len(journal_ldevs) - 1].delete_ldev(
                        journal_ldevs[-1])
        return journal_ids

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
            },
            _WAIT_SSWS: {
                'instance': self.rep_secondary,
                'remote_client': None,
                'is_secondary': True,
                'transitional_status': ['PAIR', 'PFUL', 'PFUS', 'PSUE',
                                        'SSUS'],
                'expected_status': ['SSWS'],
                'msgid': MSG.SPLIT_REPLICATION_PAIR_FAILED,
                'status_keys': ['svolStatus'],
            },
            _WAIT_SPLIT: {
                'instance': self.rep_primary,
                'remote_client': self.rep_secondary.client,
                'is_secondary': False,
                'transitional_status': ['PAIR', 'PFUL'],
                'expected_status': ['PSUS', 'SSUS', 'PSUE', 'PFUS', 'SSWS'],
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
                         is_data_reduction_force_copy,
                         do_initialcopy=True, journal_ids=None):
        """Create a replication pair."""
        created_journal_ids = []
        copy_group_name = self._create_rep_copy_group_name(pvol)

        @utils.synchronized_on_copy_group()
        def inner(self, remote_client, copy_group_name, secondary_storage_id,
                  conf, copyPace, journal_ids, parent):
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
                'isDataReductionForceCopy': is_data_reduction_force_copy
            }
            if rep_type == parent.driver_info['mirror_attr']:
                body['quorumDiskId'] = conf.hitachi_quorum_disk_id
                body['copyPace'] = copyPace
                if is_new_copy_grp:
                    body['muNumber'] = 0
            if (rep_type == parent.driver_info.get('rep_type_async') and
                    is_new_copy_grp):
                body['muNumber'] = conf.hitachi_replication_mun
                if not journal_ids:
                    journal_ids = parent.create_journals(volume,
                                                         copy_group_name)
                    created_journal_ids.extend(journal_ids)
                body['pvolJournalId'], body['svolJournalId'] = journal_ids
            self.add_remote_copypair(remote_client, body)

        try:
            inner(
                self.rep_primary.client, self.rep_secondary.client,
                copy_group_name, self.rep_secondary.storage_id,
                self.rep_secondary.conf, self._get_rep_copy_speed(),
                journal_ids, self)
            self._wait_pair_status_change(
                copy_group_name, pvol, svol, rep_type, _WAIT_PAIR)
        except exception.VolumeDriverException:
            with excutils.save_and_reraise_exception():
                if created_journal_ids:
                    self._delete_journals(created_journal_ids)

    def _create_rep_ldev_and_pair(
            self, volume, extra_specs, rep_type, pvol=None):
        """Create volume and Replication pair."""
        capacity_saving = None
        if self.driver_info.get('driver_dir_name'):
            capacity_saving = extra_specs.get(
                self.driver_info['driver_dir_name'] + ':capacity_saving')
        is_data_reduction_force_copy = (
            capacity_saving == 'deduplication_compression')
        if (self.conf.hitachi_mirror_storage_id
                and is_data_reduction_force_copy):
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
            if rep_type == self.driver_info['mirror_attr'] and self.\
                    rep_primary.conf.\
                    hitachi_set_mirror_reserve_attribute:
                self.rep_secondary.client.assign_virtual_ldevid(svol)
            self._create_rep_pair(volume, pvol, svol, rep_type,
                                  is_data_reduction_force_copy)
        except Exception:
            with excutils.save_and_reraise_exception():
                if svol is not None:
                    self.rep_secondary.terminate_pair_connection(svol)
                    if rep_type == self.driver_info['mirror_attr'] and self.\
                            rep_primary.conf.\
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
        if self._active_backend_id:
            return self._convert_model_update(
                self.rep_secondary.create_volume(volume))
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
        if volume.is_replicated():
            _check_rep_ldev(self, volume, 'create a volume')
            rep_type = _get_rep_type(self, extra_specs)
            pldev, sldev = self._create_rep_ldev_and_pair(
                volume, extra_specs, rep_type)
            provider_location = _pack_rep_provider_location(
                pldev, sldev, rep_type)
            return {
                'provider_location': provider_location,
                'replication_status': fields.ReplicationStatus.ENABLED
            }
        return self._convert_model_update(
            self.rep_primary.create_volume(volume))

    def _verify_ldev(self, obj, operation, group_info=''):
        """Check ldev site for operation."""
        if (self._active_backend_id and _get_ldev_site(obj) == _PRIMARY or
                not self._active_backend_id and _get_ldev_site(obj) ==
                _SECONDARY):
            provider_location = obj.get('provider_location')
            obj_name = 'volume' if isinstance(
                obj, cinder_volume.Volume) else 'snapshot'
            if not self._active_backend_id:
                execution_site = utils.PRIMARY_STR
                ldev_site = utils.SECONDARY_STR
                ldev = json.loads(provider_location)['sldev']
            else:
                execution_site = utils.SECONDARY_STR
                ldev_site = utils.PRIMARY_STR
                ldev = (provider_location if provider_location.isdigit() else
                        json.loads(provider_location)['pldev'])
            msg = utils.output_log(
                MSG.OTHER_SITE_ERROR,
                operation=operation, execution_site=execution_site,
                ldev_site=ldev_site, group_info=group_info, obj=obj_name,
                obj_id=obj.id, ldev=ldev)
            self.raise_error(msg)

    def _has_rep_pair(self, ldev, instance=None, ldev_info=None):
        """Return if the specified LDEV has a replication pair.

        :param int ldev: The LDEV ID
        :param dict ldev_info: LDEV info
        :return: True if the LDEV status is normal and the LDEV has a
        replication pair, False otherwise
        :rtype: bool
        """
        instance = instance or self._get_active_backend()
        if ldev_info is None:
            ldev_info = instance.get_ldev_info(['status', 'attributes'], ldev)
        return (ldev_info['status'] == rest.NORMAL_STS and
                (rest.REP_ATTR in ldev_info['attributes'] or
                self.driver_info['mirror_attr'] in ldev_info['attributes']))

    def _get_rep_pair_info(self, pldev, sldev=None, ldev_info=None):
        """Return replication pair info.

        :param int pldev: The ID of the LDEV(P-VOL in case of a pair)
        :param dict ldev_info: LDEV info
        :return: replication pair info. An empty dict if the LDEV does not
        have a pair.
        :rtype: dict
        """
        pair_info = {}
        if sldev is not None:
            ldev = sldev
            instance = self.rep_secondary
        else:
            ldev = pldev
            instance = self._get_active_backend()
        if not self._has_rep_pair(ldev, instance, ldev_info):
            return pair_info
        self._require_rep_secondary()
        copy_group_name = self._create_rep_copy_group_name(pldev)
        if sldev is not None:
            pair = self.rep_secondary.client.get_remote_copypair(
                None, copy_group_name, pldev, sldev, is_secondary=True)
            if not pair:
                return pair_info
        else:
            pairs = self.rep_primary.client.get_remote_copy_grp(
                self.rep_secondary.client,
                copy_group_name).get('copyPairs', [])
            for pair in pairs:
                if (pair.get('replicationType') in
                        [self.driver_info.get('rep_type_async'),
                         self.driver_info['mirror_attr']] and
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

    def _get_journal_ids(self, copy_group_name):
        pairs = self.rep_primary.client.get_remote_copy_grp(
            self.rep_secondary.client, copy_group_name).get('copyPairs', [])
        return pairs[0].get('pvolJournalId'), pairs[0].get('svolJournalId')

    def _split_rep_pair(self, pvol, svol):
        copy_group_name = self._create_rep_copy_group_name(pvol)
        rep_type = self.driver_info['mirror_attr']
        self.rep_primary.client.split_remote_copypair(
            self.rep_secondary.client, copy_group_name, pvol, svol, rep_type)
        self._wait_pair_status_change(
            copy_group_name, pvol, svol, rep_type, _WAIT_PSUS)

    def _delete_rep_pair(
            self, pvol, svol, do_split=False, delete_journal=False):
        """Delete a replication pair."""
        copy_group_name = self._create_rep_copy_group_name(pvol)
        if delete_journal:
            journal_ids = self._get_journal_ids(copy_group_name)
        if do_split:
            self._split_rep_pair(pvol, svol)
        self.rep_primary.client.delete_remote_copypair(
            self.rep_secondary.client, copy_group_name, pvol, svol)
        if delete_journal:
            rtn = self.rep_primary.client.get_remote_copy_grp(
                self.rep_secondary.client, copy_group_name,
                ignore_message_id=[_MSGID_INSTANCE_CANNOT_OPERATED])
            if rtn.get('messageId') == _MSGID_INSTANCE_CANNOT_OPERATED:
                self._delete_journals(journal_ids)

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
        rep_type = None
        if not pvol_is_invalid:
            pair_info = self._get_rep_pair_info(pvol, ldev_info=pvol_info)
            if pair_info:
                pair_exists = True
                # Because this pair is a valid P-VOL's pair, we need to delete
                # it and its LDEVs. The LDEV ID of the S-VOL to be deleted is
                # uniquely determined from the pair info. Therefore, there is
                # no need to get it from provider_location or to validate the
                # S-VOL by comparing the volume ID with the S-VOL's label.
                svol = pair_info['svol_info'][0]['ldev']
                svol_is_invalid = False
                rep_type = pair_info['svol_info'][0]['rep_type']
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
        return svol, pvol_is_invalid, svol_is_invalid, pair_exists, rep_type

    def delete_volume(self, volume):
        """Delete the specified volume."""
        self._require_rep_primary()
        self._verify_ldev(volume, 'delete a volume')
        ldev = self._get_active_backend().get_ldev(volume)
        if ldev is None:
            self._get_active_backend().output_log(
                MSG.INVALID_LDEV_FOR_DELETION, method='delete_volume',
                id=volume.id)
            return
        if self._active_backend_id:
            if self._has_rep_pair(ldev):
                msg = self.rep_secondary.output_log(
                    MSG.REPLICATION_PAIR_ERROR,
                    operation='delete a volume', volume=volume.id,
                    snapshot_info='', ldev=ldev)
                self.raise_error(msg)
            self.rep_secondary.delete_volume(volume)
            return
        # Run pre-check.
        svol, pvol_is_invalid, svol_is_invalid, pair_exists, rep_type = (
            self._delete_volume_pre_check(volume))
        # Delete the pair if it exists.
        if pair_exists:
            self._delete_rep_pair(
                ldev, svol,
                rep_type == self.driver_info['mirror_attr'],
                rep_type != self.driver_info['mirror_attr'])
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
        pair_info = self._get_rep_pair_info(ldev, ldev_info=ldev_info)
        if pair_info:
            self._delete_rep_pair(
                ldev, pair_info['svol_info'][0]['ldev'],
                pair_info['svol_info'][0]['rep_type'] ==
                self.driver_info['mirror_attr'],
                pair_info['svol_info'][0]['rep_type'] !=
                self.driver_info['mirror_attr'])
            th = greenthread.spawn(self.rep_secondary.delete_ldev,
                                   pair_info['svol_info'][0]['ldev'])
            try:
                self.rep_primary.delete_ldev(ldev)
            finally:
                th.wait()
        else:
            self.rep_primary.delete_ldev(ldev)

    def _create_rep_volume_from_src(
            self, volume, extra_specs, src, src_type, operation, rep_type):
        """Create a replication volume from a volume or snapshot and return

        its properties.
        """
        if rep_type != self.driver_info['mirror_attr']:
            _check_rep_ldev(self, volume, operation)
        data = self.rep_primary.create_volume_from_src(
            volume, src, src_type, is_rep=True)
        new_ldev = self.rep_primary.get_ldev(data)
        sldev = self._create_rep_ldev_and_pair(
            volume, extra_specs, rep_type, new_ldev)[1]
        provider_location = _pack_rep_provider_location(
            new_ldev, sldev, rep_type)
        if rep_type != self.driver_info['mirror_attr']:
            return {
                'provider_location': provider_location,
                'replication_status': fields.ReplicationStatus.ENABLED
            }
        else:
            return {
                'provider_location': provider_location,
            }

    def _create_volume_from_src(self, volume, src, src_type):
        """Create a volume from a volume or snapshot and return its properties.

        """
        self._require_rep_primary()
        operation = ('create a volume from a %s' % src_type)
        self._verify_ldev(src, operation)
        if self._active_backend_id:
            return self._convert_model_update(
                self.rep_secondary.create_volume_from_src(
                    volume, src, src_type))
        extra_specs = self.rep_primary.get_volume_extra_specs(volume)
        if self._is_mirror_spec(extra_specs):
            self._require_rep_secondary()
            return self._create_rep_volume_from_src(
                volume, extra_specs, src, src_type, operation,
                self.driver_info['mirror_attr'])
        if volume.is_replicated():
            return self._create_rep_volume_from_src(
                volume, extra_specs, src, src_type, operation,
                _get_rep_type(self, extra_specs))
        return self._convert_model_update(
            self.rep_primary.create_volume_from_src(volume, src, src_type))

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
        self._verify_ldev(snapshot.volume, 'create a snapshot')
        model_update = self._convert_model_update(
            self._get_active_backend().create_snapshot(snapshot),
            is_snapshot=True)
        return model_update

    def delete_snapshot(self, snapshot):
        """Delete the specified snapshot."""
        self._require_rep_primary()
        self._verify_ldev(snapshot, 'delete a snapshot')
        self._get_active_backend().delete_snapshot(snapshot)

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
            self._verify_ldev(volume, 'initialize volume connection')
            return self._get_active_backend().initialize_connection(
                volume, connector, is_snapshot=is_snapshot)

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
            self._verify_ldev(volume, 'terminate volume connection')
            return self._get_active_backend().terminate_connection(
                volume, connector)

    def _extend_pair_volume(self, volume, new_size, ldev, pair_info):
        """Extend the specified  replication volume to the specified size."""
        extra_specs = self.rep_primary.get_volume_extra_specs(volume)
        capacity_saving = extra_specs.get(
            self.driver_info['driver_dir_name'] + ':capacity_saving')
        is_data_reduction_force_copy = (
            capacity_saving == 'deduplication_compression')
        if self.conf.hitachi_mirror_storage_id:
            rep_type = self.driver_info['mirror_attr']
        else:
            rep_type = _get_rep_type(self, extra_specs)
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
        if self.conf.hitachi_mirror_storage_id:
            journal_ids = None
        else:
            copy_group_name = self._create_rep_copy_group_name(ldev)
            journal_ids = self._get_journal_ids(copy_group_name)
        if not self.conf.safe_get(self.driver_info['param_prefix'] +
                                  '_extend_snapshot_volumes'):
            # If the volume has a snapshot, P-VOL is not expandable because it
            # is a P-VOL of a TI pair, while S-VOL is expandable because it is
            # not in a TI pair because a snapshot is not created in the
            # secondary storage. Expanding only the S-VOL makes it difficult to
            # restore the pair after an error occurs. To avoid this situation,
            # we check if P-VOL is expandable before expanding both LDEVs. The
            # following method raises an exception if P-VOL is in a TI pair,
            # and thus we can prevent expanding only S-VOL. Contrary to its
            # name, this method does not actually delete a TI pair in this
            # context because the P-VOL of a GAD/UR pair cannot be the S-VOL of
            # a TI pair.
            self.rep_primary.delete_pair(ldev)
        self._delete_rep_pair(
            ldev, pair_info['svol_info'][0]['ldev'],
            rep_type == self.driver_info['mirror_attr'], delete_journal=False)
        thread = greenthread.spawn(
            self.rep_secondary.extend_volume, volume, new_size)
        try:
            self.rep_primary.extend_volume(volume, new_size)
        finally:
            thread.wait()
        self._create_rep_pair(
            volume, pair_info['pvol'], pair_info['svol_info'][0]['ldev'],
            rep_type, is_data_reduction_force_copy, do_initialcopy=False,
            journal_ids=journal_ids)

    def extend_volume(self, volume, new_size):
        """Extend the specified volume to the specified size."""
        self._require_rep_primary()
        self._verify_ldev(volume, 'extend a volume')
        ldev = self._get_active_backend().get_ldev(volume)
        if ldev is None:
            msg = self._get_active_backend().output_log(
                MSG.INVALID_LDEV_FOR_EXTENSION, volume_id=volume.id)
            self.raise_error(msg)
        if self._active_backend_id:
            if self._has_rep_pair(ldev):
                msg = self.rep_secondary.output_log(
                    MSG.REPLICATION_PAIR_ERROR,
                    operation='extend a volume', volume=volume.id,
                    snapshot_info='', ldev=ldev)
                self.raise_error(msg)
            self.rep_secondary.extend_volume(volume, new_size)
            return
        pair_info = self._get_rep_pair_info(ldev)
        if pair_info:
            self._extend_pair_volume(volume, new_size, ldev, pair_info)
        else:
            self.rep_primary.extend_volume(volume, new_size)

    def manage_existing(self, volume, existing_ref):
        """Return volume properties which Cinder needs to manage the volume."""
        self._require_rep_primary()
        return self._convert_model_update(
            self._get_active_backend().manage_existing(volume, existing_ref))

    def manage_existing_get_size(self, volume, existing_ref):
        """Return the size[GB] of the specified volume."""
        self._require_rep_primary()
        if not self.conf.hitachi_mirror_storage_id:
            if volume.is_replicated():
                msg = utils.output_log(
                    MSG.MANAGE_REPLICATION_VOLUME_ERROR,
                    replication_enabled=volume.volume_type.
                    extra_specs['replication_enabled'],
                    source_id=existing_ref.get('source-id'), volume=volume.id,
                    volume_type=volume.volume_type.name)
                self.raise_error(msg)
            ldev = common.str2int(existing_ref.get('source-id'))
            if ldev is None:
                msg = utils.output_log(MSG.INVALID_LDEV_FOR_MANAGE)
                raise exception.ManageExistingInvalidReference(
                    existing_ref=existing_ref, reason=msg)
            if self._has_rep_pair(ldev):
                msg = self._get_active_backend().output_log(
                    MSG.REPLICATION_PAIR_ERROR,
                    operation='manage a volume', volume=volume.id,
                    snapshot_info='', ldev=ldev)
                self.raise_error(msg)
        return self._get_active_backend().manage_existing_get_size(
            volume, existing_ref)

    def unmanage(self, volume):
        """Prepare the volume for removing it from Cinder management."""
        self._require_rep_primary()
        self._verify_ldev(volume, 'unmanage a volume')
        ldev = self._get_active_backend().get_ldev(volume)
        if ldev is None:
            self._get_active_backend().output_log(
                MSG.INVALID_LDEV_FOR_DELETION,
                method='unmanage', id=volume.id)
            return
        if self._has_rep_pair(ldev):
            msg = self._get_active_backend().output_log(
                MSG.REPLICATION_PAIR_ERROR,
                operation='unmanage a volume', volume=volume.id,
                snapshot_info='', ldev=ldev)
            self.raise_error(msg)
        self._get_active_backend().unmanage(volume)

    def discard_zero_page(self, volume):
        self._require_rep_primary()
        self._verify_ldev(volume, 'discard zero-data pages of a volume')
        ldev = self._get_active_backend().get_ldev(volume)
        if self._has_rep_pair(ldev):
            if self.conf.hitachi_mirror_storage_id:
                self._require_rep_secondary()
                th = greenthread.spawn(
                    self.rep_secondary.discard_zero_page, volume)
                try:
                    self.rep_primary.discard_zero_page(volume)
                finally:
                    th.wait()
        else:
            self._get_active_backend().discard_zero_page(volume)

    def unmanage_snapshot(self, snapshot):
        if not self.rep_primary:
            return self.rep_secondary.unmanage_snapshot(snapshot)
        else:
            return self._get_active_backend().unmanage_snapshot(snapshot)

    def retype(self, ctxt, volume, new_type, diff, host):
        self._require_rep_primary()
        self._verify_ldev(volume, 'retype a volume')
        ldev = self._get_active_backend().get_ldev(volume)
        if ldev is None:
            msg = self._get_active_backend().output_log(
                MSG.INVALID_LDEV_FOR_VOLUME_COPY,
                type='volume', id=volume.id)
            self.raise_error(msg)
        if (self._has_rep_pair(ldev) or new_type.is_replicated() or
                self._is_mirror_spec(new_type['extra_specs'])):
            return False
        return self._get_active_backend().retype(
            ctxt, volume, new_type, diff, host)

    def migrate_volume(self, volume, host):
        self._require_rep_primary()
        self._verify_ldev(volume, 'migrate a volume')
        ldev = self._get_active_backend().get_ldev(volume)
        if ldev is None:
            msg = self._get_active_backend().output_log(
                MSG.INVALID_LDEV_FOR_VOLUME_COPY,
                type='volume', id=volume.id)
            self.raise_error(msg)
        if self._get_rep_pair_info(ldev):
            return False, None
        else:
            return self._get_active_backend().migrate_volume(volume, host)

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
        self._verify_ldev(volume, 'revert a volume to a snapshot')
        self._verify_ldev(snapshot, 'revert a volume to a snapshot')
        ldev = self._get_active_backend().get_ldev(volume)
        if self.conf.hitachi_mirror_storage_id:
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
        else:
            if ldev is None:
                msg = self._get_active_backend().output_log(
                    MSG.LDEV_NUMBER_NOT_FOUND,
                    operation='revert a volume to a snapshot',
                    obj='volume', obj_id=volume.id)
                self.raise_error(msg)
            if self._has_rep_pair(ldev):
                msg = self._get_active_backend().output_log(
                    MSG.REPLICATION_PAIR_ERROR,
                    operation='revert a volume to a snapshot',
                    volume=volume.id,
                    snapshot_info='snapshot: %s, ' % snapshot.id,
                    ldev=ldev)
                self.raise_error(msg)
            self._get_active_backend().revert_to_snapshot(volume, snapshot)

    def create_group(self):
        self._require_rep_primary()
        return self._get_active_backend().create_group()

    def delete_group(self, group, volumes):
        if self.conf.hitachi_mirror_storage_id:
            self._require_rep_primary()
            return super(HBSDREPLICATION, self).delete_group(group, volumes)
        else:
            for volume in volumes:
                self._verify_ldev(volume, 'delete a volume in a group',
                                  'group: %s, ' % group.id)
            return self._get_active_backend().delete_group(group, volumes)

    def create_group_from_src(
            self, context, group, volumes, snapshots=None, source_vols=None):
        if self.conf.hitachi_mirror_storage_id:
            self._require_rep_primary()
            return super(HBSDREPLICATION, self).create_group_from_src(
                context, group, volumes, snapshots, source_vols)
        else:
            operation = ('create a volume from a %s' %
                         ('volume in a group' if snapshots is None else
                          'snapshot in a group snapshot'))
            for obj in snapshots or source_vols:
                self._verify_ldev(obj, operation)
            model_update, volumes_model_update = (
                self._get_active_backend().create_group_from_src(
                    context, group, volumes, snapshots, source_vols))
            for volume_model_update in volumes_model_update:
                self._convert_model_update(volume_model_update)
            return model_update, volumes_model_update

    def update_group(self, group, add_volumes=None):
        if self.conf.hitachi_mirror_storage_id:
            self._require_rep_primary()
            return self.rep_primary.update_group(group, add_volumes)
        else:
            for volume in add_volumes:
                self._verify_ldev(volume, 'add a volume to a group',
                                  'group: %s, ' % group.id)
                ldev = self._get_active_backend().get_ldev(volume)
                if ldev is None:
                    msg = self._get_active_backend().output_log(
                        MSG.LDEV_NOT_EXIST_FOR_ADD_GROUP,
                        volume_id=volume.id, group='group', group_id=group.id)
                    self.raise_error(msg)
                if self._has_rep_pair(ldev):
                    extra_specs = (self._get_active_backend().
                                   get_volume_extra_specs(volume))
                    rep_type = _get_rep_type(self, extra_specs)
                    msg = self._get_active_backend().output_log(
                        MSG.REPLICATION_VOLUME_ADD_GROUP_ERROR,
                        rep_type=rep_type, volume_id=volume.id, ldev=ldev,
                        group_id=group.id)
                    self.raise_error(msg)
            return self._get_active_backend().update_group(group, add_volumes)

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        if self.conf.hitachi_mirror_storage_id:
            self._require_rep_primary()
            return self.rep_primary.create_group_snapshot(
                context, group_snapshot, snapshots)
        else:
            for snapshot in snapshots:
                self._verify_ldev(snapshot.volume, 'create a group snapshot')
            rtn = self._get_active_backend().create_group_snapshot(
                context, group_snapshot, snapshots)
            for snapshot_model_update in rtn[-1]:
                if 'provider_location' in snapshot_model_update:
                    self._convert_model_update(
                        snapshot_model_update, is_snapshot=True)
            return rtn

    def delete_group_snapshot(self, group_snapshot, snapshots):
        if self.conf.hitachi_mirror_storage_id:
            self._require_rep_primary()
            return self.rep_primary.delete_group_snapshot(
                group_snapshot, snapshots)
        else:
            for snapshot in snapshots:
                self._verify_ldev(snapshot,
                                  'delete a snapshot in a group snapshot',
                                  'group snapshot: %s, ' % group_snapshot.id)
            return self._get_active_backend().delete_group_snapshot(
                group_snapshot, snapshots)

    def _get_ldevs(self, volume, is_failback=False):
        pldev = self.rep_primary.get_ldev(volume)
        sldev = (self.rep_secondary.get_ldev(volume) if
                 _get_ldev_site(volume) in (_SECONDARY, _PRIMARY_SECONDARY)
                 else None)
        if pldev is None or sldev is None:
            instance = (self.rep_primary if pldev is None else
                        self.rep_secondary)
            instance.output_log(
                MSG.NOT_LDEV_NUMBER_WARNING,
                operation='fail back a volume' if is_failback else
                'fail over a volume', obj='volume', obj_id=volume.id)
        return pldev, sldev

    def _get_rep_pairs(self, volumes):
        rep_pairs = []
        for volume in volumes:
            if volume.replication_status in (
                    fields.ReplicationStatus.FAILED_OVER,
                    fields.ReplicationStatus.FAILOVER_ERROR):
                pldev, sldev = self._get_ldevs(volume, is_failback=True)
                if pldev is None or sldev is None:
                    continue
                rep_pairs.append((pldev, sldev))
        return rep_pairs

    def _extract_my_copy_grps(self, remote_copy_groups):
        my_groups = []
        copy_group_name = self._create_rep_copy_group_name(0)
        my_prefix = copy_group_name[:len(copy_group_name) - 2]
        for remote_copy_group in remote_copy_groups:
            if remote_copy_group['copyGroupName'].startswith(my_prefix):
                my_groups.append(remote_copy_group)
        return my_groups

    def _get_failback_target_pairs(self, copy_group_name, rep_pairs):
        try:
            pairs = (
                self.rep_primary.client.get_remote_copy_grp(
                    self.rep_secondary.client, copy_group_name).get(
                        'copyPairs', []))
        except exception.VolumeDriverException:
            self.rep_primary.output_log(
                MSG.COPY_PAIR_CANNOT_RETRIEVED, copy_grp=copy_group_name)
            return None
        failback_target_pairs = []
        for pair in pairs:
            if (pair['pvolLdevId'], pair['svolLdevId']) not in rep_pairs:
                utils.output_log(
                    MSG.UNMANAGE_LDEV_EXIST_WARNING,
                    copy_grp=copy_group_name, pvol=pair['pvolLdevId'],
                    svol=pair['svolLdevId'],
                    config_group=self.conf.config_group)
                return None
            if pair.get('svolStatus') != 'SSWS':
                utils.output_log(
                    MSG.INVALID_COPY_GROUP_STATUS,
                    copy_grp=copy_group_name, pvol=pair['pvolLdevId'],
                    pvol_status=pair.get('pvolStatus'),
                    svol=pair['svolLdevId'],
                    svol_status=pair.get('svolStatus'))
                return None
            failback_target_pairs.append(
                (pair['pvolLdevId'], pair['svolLdevId'],
                 pair['replicationType'])
            )
        return failback_target_pairs

    def _failback_copy_group(self, copy_group_name, failback_target_pairs):
        rep_type = failback_target_pairs[0][2]
        try:
            self.rep_primary.client.split_remote_copy_grp(
                self.rep_secondary.client, copy_group_name, rep_type)
            for pvol, svol, _ in failback_target_pairs:
                self._wait_pair_status_change(copy_group_name, pvol, svol,
                                              rep_type, _WAIT_SPLIT)
            self.rep_secondary.client.resync_remote_copy_grp(
                self.rep_primary.client, copy_group_name, rep_type, True, True)
            for pvol, svol, _ in failback_target_pairs:
                self._wait_pair_status_change(copy_group_name, pvol, svol,
                                              rep_type, _WAIT_PAIR)
            self.rep_primary.client.split_remote_copy_grp(
                self.rep_secondary.client, copy_group_name, rep_type)
            for pvol, svol, _ in failback_target_pairs:
                self._wait_pair_status_change(copy_group_name, pvol, svol,
                                              rep_type, _WAIT_PSUS)
            self.rep_primary.client.resync_remote_copy_grp(
                self.rep_secondary.client, copy_group_name, rep_type, True)
            for pvol, svol, _ in failback_target_pairs:
                self._wait_pair_status_change(copy_group_name, pvol, svol,
                                              rep_type, _WAIT_PAIR)
        except exception.VolumeDriverException:
            utils.output_log(
                MSG.FAILOVER_FAILBACK_WARNING,
                direction='back', obj='copy group', operation='failback',
                obj_id=copy_group_name)
            return False
        return True

    def _get_failback_volume_update(self, volumes, failback_success_pairs):
        volume_updates = []
        for volume in volumes:
            volume_update = {'volume_id': volume.id}
            pvol = self.rep_primary.get_ldev(volume)
            svol = self.rep_secondary.get_ldev(volume)
            if (pvol, svol) in [(pldev, sldev) for (pldev, sldev, _) in
                                failback_success_pairs]:
                volume_update['updates'] = {
                    'replication_status': fields.ReplicationStatus.ENABLED}
                for snapshot in volume.snapshots:
                    if _get_ldev_site(snapshot) == _SECONDARY:
                        snapshot.status = fields.SnapshotStatus.ERROR
                        snapshot.save()
            else:
                volume_update['updates'] = {'status': 'error'}
                if volume.replication_status in (
                        fields.ReplicationStatus.FAILED_OVER,
                        fields.ReplicationStatus.FAILOVER_ERROR):
                    volume_update['updates']['replication_status'] = (
                        fields.ReplicationStatus.FAILOVER_ERROR)
            volume_updates.append(volume_update)
        return volume_updates

    def _failback_volume(self, volumes):
        failback_success_pairs = []
        rep_pairs = self._get_rep_pairs(volumes)
        if rep_pairs:
            try:
                remote_copy_grps = (
                    self.rep_primary.client.get_remote_copy_grps(
                        self.rep_secondary.client))
            except Exception:
                msg = self.rep_primary.output_log(
                    MSG.COPY_GROUP_CANNOT_RETRIEVED,
                    config_group=self.conf.config_group)
                raise exception.UnableToFailOver(reason=msg)
            remote_copy_grps = self._extract_my_copy_grps(remote_copy_grps)
            for remote_copy_grp in remote_copy_grps:
                copy_group_name = remote_copy_grp['copyGroupName']
                failback_target_pairs = self._get_failback_target_pairs(
                    copy_group_name, rep_pairs)
                if not failback_target_pairs:
                    continue
                if not (self._failback_copy_group(
                        copy_group_name, failback_target_pairs)):
                    continue
                failback_success_pairs.extend(failback_target_pairs)
        return self._get_failback_volume_update(volumes,
                                                failback_success_pairs)

    def _failover_pair_volume(self, volume):
        pldev, sldev = self._get_ldevs(volume)
        if pldev is None or sldev is None:
            return False
        pair_info = self._get_rep_pair_info(pldev, sldev)
        if not pair_info:
            self.rep_secondary.output_log(
                MSG.NOT_REPLICATION_PAIR_WARNING, volume=volume.id, ldev=sldev)
            return False
        if pair_info['svol_info'][0]['svol_status'] != 'PAIR':
            utils.output_log(
                MSG.NOT_SYNCHRONIZED_WARNING,
                volume=volume.id, pvol=pldev, svol=sldev,
                svol_status=pair_info['svol_info'][0]['svol_status'])
        if pair_info['svol_info'][0]['svol_status'] != 'SSWS':
            copy_group_name = self._create_rep_copy_group_name(pldev)
            extra_specs = self.rep_secondary.get_volume_extra_specs(volume)
            rep_type = _get_rep_type(self, extra_specs)
            self.rep_secondary.client.takeover_remote_copypair(
                copy_group_name, pldev, sldev)
            self._wait_pair_status_change(copy_group_name, pldev, sldev,
                                          rep_type, _WAIT_SSWS)
        return True

    def _failover_volume(self, volumes):
        failover_success_volumes = []
        for volume in volumes:
            if volume.replication_status in (
                    fields.ReplicationStatus.ENABLED,
                    fields.ReplicationStatus.FAILOVER_ERROR):
                try:
                    if self._failover_pair_volume(volume):
                        failover_success_volumes.append(volume)
                except exception.VolumeDriverException:
                    utils.output_log(
                        MSG.FAILOVER_FAILBACK_WARNING,
                        direction='over', obj='volume',
                        operation='failover', obj_id=volume.id)
        return _get_failover_volume_update(volumes, failover_success_volumes)

    def failover(self, volumes, secondary_id=None):
        if ((secondary_id not in (None,
                                  _REP_FAILBACK,
                                  self.rep_secondary.backend_id)) or
                (secondary_id ==
                    _REP_FAILBACK and not self._active_backend_id) or
                (secondary_id != _REP_FAILBACK and self._active_backend_id)):
            direction = 'back' if secondary_id == _REP_FAILBACK else 'over'
            execution_site = (utils.SECONDARY_STR if self._active_backend_id
                              else utils.PRIMARY_STR)
            msg = utils.output_log(
                MSG.INVALID_DESTINATION,
                direction=direction, execution_site=execution_site,
                specified_backend_id=secondary_id,
                defined_backend_id=self.rep_secondary.backend_id)
            raise exception.InvalidReplicationTarget(reason=msg)
        if secondary_id == _REP_FAILBACK:
            try:
                self.rep_primary.do_setup(self.rep_primary.ctxt)
            except Exception:
                msg = self.rep_primary.output_log(
                    MSG.FAILED_FAILBACK, site=utils.PRIMARY_STR)
                raise exception.UnableToFailOver(reason=msg)
            return secondary_id, self._failback_volume(volumes), []
        return (self.rep_secondary.backend_id, self._failover_volume(volumes),
                [])

    def failover_completed(self, secondary_id=None):
        self._active_backend_id = ('' if secondary_id == _REP_FAILBACK else
                                   self.rep_secondary.backend_id)

    def failover_host(self, volumes, secondary_id=None):
        backend_id, volumes_update, groups_update = self.failover(
            volumes, secondary_id)
        self.failover_completed(secondary_id)
        return backend_id, volumes_update, groups_update
