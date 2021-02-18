# Copyright (c) 2019 MacroSAN Technologies Co., Ltd.
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
"""Volume Drivers for MacroSAN SAN."""

from contextlib import contextmanager
import math
import re
import socket
import time
import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import strutils
from oslo_utils import timeutils

from cinder import context
from cinder.coordination import synchronized
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.macrosan import config
from cinder.volume.drivers.macrosan import devop_client
from cinder.volume.drivers.san import san
from cinder.volume import qos_specs
from cinder.volume import volume_types
from cinder.volume import volume_utils
from cinder.zonemanager import utils as fczm_utils

version = '1.0.1'
lock_name = 'MacroSAN'

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
CONF.register_opts(config.macrosan_opts, group=configuration.SHARED_CONF_GROUP)


@contextmanager
def ignored(*exceptions):
    try:
        yield
    except exceptions:
        pass


def record_request_id(fn):
    def _record_request_id(*vargs, **kv):
        ctx = context.context.get_current()
        devop_client.context_request_id = ctx.request_id

        return fn(*vargs, **kv)
    return _record_request_id


def replication_synced(params):
    return (params['replication_enabled'] and
            params['replication_mode'] == 'sync')


class MacroSANBaseDriver(driver.VolumeDriver):
    """Base driver for MacroSAN SAN."""

    CI_WIKI_NAME = 'MacroSAN_Volume_CI'

    def __init__(self, *args, **kwargs):
        """Initialize the driver."""
        super(MacroSANBaseDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(config.macrosan_opts)
        self.configuration.append_config_values(san.san_opts)
        self._stats = {}
        self.use_multipath = True
        self.owners = ['SP1', 'SP2']
        self.owner_idx = 0
        self.volume_backend_name = (
            self.configuration.safe_get('volume_backend_name') or 'MacroSAN')

        self.username = self.configuration.san_login
        self.passwd = self.configuration.san_password
        self.sp1_ipaddr, self.sp2_ipaddr = (
            self.configuration.san_ip.replace(' ', '').split(","))
        self.login_info = self.username + self.passwd

        if self.configuration.macrosan_sdas_ipaddrs:
            self.sdas_username = self.configuration.macrosan_sdas_username
            self.sdas_passwd = self.configuration.macrosan_sdas_password
            self.sdas_sp1_ipaddr, self.sdas_sp2_ipaddr = (
                self.configuration.macrosan_sdas_ipaddrs)
            self.sdas_sp1_ipaddr = (
                self.sdas_sp1_ipaddr.replace('/', ',').replace(' ', ''))
            self.sdas_sp2_ipaddr = (
                self.sdas_sp2_ipaddr.replace('/', ',').replace(' ', ''))
            self.sdas_login_info = self.sdas_username + self.sdas_passwd

        if self.configuration.macrosan_replication_ipaddrs:
            self.rep_username = (
                self.configuration.macrosan_replication_username)

            self.rep_passwd = self.configuration.macrosan_replication_password
            self.rep_sp1_ipaddr, self.rep_sp2_ipaddr = (
                self.configuration.macrosan_replication_ipaddrs)
            self.rep_sp1_ipaddr = (
                self.rep_sp1_ipaddr.replace('/', ',').replace(' ', ''))
            self.rep_sp2_ipaddr = (
                self.rep_sp2_ipaddr.replace('/', ',').replace(' ', ''))
            self.replica_login_info = self.rep_username + self.rep_passwd
            self.replication_params = {
                'destination':
                    {'sp1': self.configuration.
                        macrosan_replication_destination_ports[0],
                     'sp2': self.configuration.
                     macrosan_replication_destination_ports[1]}}

        self.client = None
        self.replica_client = None
        self.sdas_client = None
        self.storage_protocol = None
        self.device_uuid = None
        self.client_info = dict()

        self.lun_params = {}
        self.lun_mode = self.configuration.san_thin_provision
        if self.lun_mode:
            self.lun_params = (
                {'extent-size':
                    self.configuration.macrosan_thin_lun_extent_size,
                 'low-watermark':
                     self.configuration.macrosan_thin_lun_low_watermark,
                 'high-watermark':
                     self.configuration.macrosan_thin_lun_high_watermark})
        self.pool = self.configuration.macrosan_pool

        self.force_unmap_itl_when_deleting = (
            self.configuration.macrosan_force_unmap_itl)
        self.snapshot_resource_ratio = (
            self.configuration.macrosan_snapshot_resource_ratio)
        global timing_on
        timing_on = self.configuration.macrosan_log_timing

        self.initialize_iscsi_info()

    def _size_str_to_int(self, size_in_g):
        if int(size_in_g) == 0:
            return 1
        return int(size_in_g)

    def _volume_name(self, volume):
        try:
            lun_uuid = re.search(r'macrosan uuid:(.+)',
                                 volume['provider_location']).group(1)
            return self.client.get_lun_name(lun_uuid)
        except Exception:
            return volume['id']

    def _snapshot_name(self, snapshotid):
        return snapshotid.replace('-', '')[:31]

    def initialize_iscsi_info(self):
        sp1_port, sp2_port = \
            self.configuration.macrosan_client_default.split(';')
        host = socket.gethostname()
        self.client_info['default'] = {'client_name': host,
                                       'sp1_port':
                                           sp1_port.replace(' ', ''),
                                       'sp2_port':
                                           sp2_port.replace(' ', '')}
        client_list = self.configuration.macrosan_client
        if client_list:
            for i in client_list:
                client = i.strip('(').strip(')').split(";")
                host, client_name, sp1_port, sp2_port = [j.strip() for j
                                                         in client]
                self.client_info[host] = (
                    {'client_name': client_name,
                     'sp1_port': sp1_port.replace(' ', '').replace('/', ','),
                     'sp2_port': sp2_port.replace(' ', '').replace('/', ',')})

    def _get_client_name(self, host):
        if host in self.client_info:
            return self.client_info[host]['client_name']
        return self.client_info['default']['client_name']

    @utils.synchronized('MacroSAN-Setup', external=True)
    @record_request_id
    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        LOG.debug('Enter in Macrosan do_setup.')
        self.client = devop_client.Client(self.sp1_ipaddr,
                                          self.sp2_ipaddr,
                                          self.login_info)

        if self.configuration.macrosan_sdas_ipaddrs:
            self.sdas_client = (
                devop_client.Client(self.sdas_sp1_ipaddr,
                                    self.sdas_sp2_ipaddr,
                                    self.sdas_login_info))

        if self.configuration.macrosan_replication_ipaddrs:
            self.replica_client = (
                devop_client.Client(self.rep_sp1_ipaddr,
                                    self.rep_sp2_ipaddr,
                                    self.replica_login_info))
        self.device_uuid = self.client.get_device_uuid()
        self._do_setup()
        LOG.debug('MacroSAN Cinder Driver setup complete.')

    def _do_setup(self):
        pass

    def _get_owner(self):
        owner = self.owners[self.owner_idx % 2]
        self.owner_idx += 1
        return owner

    def check_for_setup_error(self):
        """Check any setup error."""
        pass

    def _check_volume_params(self, params):
        if params['sdas'] and params['replication_enabled']:
            raise exception.VolumeBackendAPIException(
                data=_('sdas and replication can not be enabled at same time'))

        if params['sdas'] and self.sdas_client is None:
            raise exception.VolumeBackendAPIException(
                data=_('sdas is not configured, cannot use sdas'))

        if params['replication_enabled'] and self.replica_client is None:
            raise exception.VolumeBackendAPIException(
                data=_('replica is not configured, cannot use replication'))

    def get_raid_list(self, size):
        raids = self.client.get_raid_list(self.pool)
        free = sum(raid['free_cap'] for raid in raids)
        if size > free:
            raise exception.VolumeBackendAPIException(_('Pool has not enough'
                                                        'free capacity'))

        raids = sorted(raids, key=lambda x: x['free_cap'], reverse=True)

        selected = []
        cap = 0
        for raid in raids:
            if raid['free_cap']:
                cap += raid['free_cap']
                selected.append(raid['name'])
                if cap >= size:
                    break
        return selected

    def _create_volume(self, name, size, params, owner=None, pool=None):
        rmt_client = None
        if params['sdas']:
            rmt_client = self.sdas_client
        elif params['replication_enabled']:
            rmt_client = self.replica_client

        owner = self._get_owner() if owner is None else owner
        raids = []
        pool = self.pool if pool is None else pool

        if not params['lun_mode']:
            raids = self.client.get_raid_list_to_create_lun(pool, size)

        self.client.create_lun(name, owner, pool, raids,
                               params['lun_mode'], size, self.lun_params)

        if params['qos-strategy']:
            try:
                self.client.enable_lun_qos(name, params['qos-strategy'])
            except Exception:
                self.client.delete_lun(name)
                raise exception.VolumeBackendAPIException(
                    _('Enable lun qos failed.'))

        if params['sdas'] or params['replication_enabled']:
            res_size = int(max(int(size) * self.snapshot_resource_ratio, 1))
            try:
                raids = self.client.get_raid_list_to_create_lun(pool,
                                                                res_size)
                self.client.setup_snapshot_resource(name, res_size, raids)
            except Exception:
                with excutils.save_and_reraise_exception():
                    self.client.delete_lun(name)

            try:
                raids = []
                if not params['lun_mode']:
                    raids = rmt_client.get_raid_list_to_create_lun(
                        pool, size)

                rmt_client.create_lun(name, owner, pool, raids,
                                      params['lun_mode'], size,
                                      self.lun_params)
            except Exception:
                with excutils.save_and_reraise_exception():
                    self.client.delete_snapshot_resource(name)
                    self.client.delete_lun(name)

            try:
                raids = rmt_client.get_raid_list_to_create_lun(pool,
                                                               res_size)
                rmt_client.setup_snapshot_resource(name, res_size, raids)
            except Exception:
                with ignored(Exception):
                    rmt_client.delete_lun(name)
                with excutils.save_and_reraise_exception():
                    self.client.delete_snapshot_resource(name)
                    self.client.delete_lun(name)

            if params['sdas'] or replication_synced(params):
                try:
                    self.client.create_dalun(name)
                except Exception:
                    with ignored(Exception):
                        rmt_client.delete_snapshot_resource(name)
                        rmt_client.delete_lun(name)
                    with excutils.save_and_reraise_exception():
                        self.client.delete_snapshot_resource(name)
                        self.client.delete_lun(name)
            elif params['replication_mode'] == 'async':
                destination = self.replication_params['destination']
                sp1_ipaddr = rmt_client.get_port_ipaddr(destination['sp1'])
                sp2_ipaddr = rmt_client.get_port_ipaddr(destination['sp2'])

                try:
                    self.client.enable_replication(name, sp1_ipaddr,
                                                   sp2_ipaddr)
                    self.client.startscan_replication(name)
                except Exception:
                    with ignored(Exception):
                        rmt_client.delete_snapshot_resource(name)
                        rmt_client.delete_lun(name)
                    with excutils.save_and_reraise_exception():
                        self.client.delete_snapshot_resource(name)
                        self.client.delete_lun(name)

        lun_uuid = self.client.get_lun_uuid(name)
        return {'provider_location': 'macrosan uuid:%s' % lun_uuid}

    def _parse_qos_strategy(self, volume_type):
        qos_specs_id = volume_type.get('qos_specs_id')

        if qos_specs_id is None:
            return ''

        ctx = context.get_admin_context()
        specs = qos_specs.get_qos_specs(ctx, qos_specs_id)['specs']

        return specs.pop('qos-strategy', '').strip() if specs else ''

    def _default_volume_params(self):
        params = {
            'qos-strategy': '',
            'replication_enabled': False,
            'replication_mode': 'async',
            'sdas': False,
            'lun_mode': self.lun_mode
        }
        return params

    def _parse_volume_params(self, volume):
        params = self._default_volume_params()

        if volume.volume_type_id is None:
            return params

        ctx = context.get_admin_context()
        volume_type = volume_types.get_volume_type(ctx, volume.volume_type_id)

        params['qos-strategy'] = self._parse_qos_strategy(volume_type)

        specs = dict(volume_type).get('extra_specs')
        for k, val in specs.items():
            ks = k.lower().split(':')
            if len(ks) == 2 and ks[0] != "capabilities":
                continue

            k = ks[-1]
            if k not in params:
                continue

            else:
                v = val.split()[-1]
                val_type = type(params[k]).__name__
                if val_type == 'int':
                    v = int(v)
                elif val_type == 'bool':
                    v = strutils.bool_from_string(v)
                params[k] = v

        if params['sdas']:
            params['lun_mode'] = False

        return params

    @synchronized(lock_name)
    @record_request_id
    @volume_utils.trace
    def create_volume(self, volume):
        """Create a volume."""
        name = volume['name']
        size = self._size_str_to_int(volume['size'])
        params = self._parse_volume_params(volume)
        self._check_volume_params(params)

        return self._create_volume(name, size, params)

    def _delete_volume(self, name, params=None):
        if not self.client.lun_exists(name):
            return

        if params is None:
            params = self._default_volume_params()

        if self.force_unmap_itl_when_deleting:
            self.force_terminate_connection(name, False)

        if params['sdas'] or replication_synced(params):
            if self.client.dalun_exists(name):
                self.client.suspend_dalun(name)
                self.client.delete_dalun(name)
                with ignored(Exception):
                    self.sdas_client.delete_snapshot_resource(name)
                    self.sdas_client.delete_lun(name)
                self.client.delete_snapshot_resource(name)

        if (params['replication_enabled'] and
                params['replication_mode'] == 'async'):
            if self.client.replication_enabled(name):
                with ignored(Exception):
                    self.client.stopscan_replication(name)
                    self.client.pausereplicate(name)
                self.client.disable_replication(name)
                self.client.delete_snapshot_resource(name)

        self.client.delete_lun(name)

        try:
            migrated_name = self.client.get_lun_name_from_rename_file(name)
            if not migrated_name:
                return
            try:
                self.client.rename_lun(migrated_name, name)
            except Exception:
                LOG.warning('========== failed to rename %(migrated_name)s'
                            ' to %(name)s',
                            {'migrated_name': migrated_name, 'name': name})
        except Exception:
            return

    @synchronized(lock_name)
    @record_request_id
    @volume_utils.trace
    def delete_volume(self, volume):
        """Delete a volume."""
        name = self._volume_name(volume)
        params = self._parse_volume_params(volume)
        self._delete_volume(name, params)

    @utils.synchronized('MacroSAN-Attach-Detach', external=True)
    def _attach_volume(self, context, volume, properties, remote=False):
        return super(MacroSANBaseDriver, self)._attach_volume(context,
                                                              volume,
                                                              properties,
                                                              remote)

    @utils.synchronized('MacroSAN-Attach-Detach', external=True)
    def _detach_volume(self, context, attach_info, volume,
                       properties, force=False, remote=False,
                       ignore_errors=True):
        return super(MacroSANBaseDriver, self)._detach_volume(context,
                                                              attach_info,
                                                              volume,
                                                              properties,
                                                              force,
                                                              remote,
                                                              ignore_errors)

    def _create_snapshot(self, snapshot_name, volume_name, volume_size):
        size = int(max(int(volume_size) * self.snapshot_resource_ratio, 1))
        raids = self.client.get_raid_list_to_create_lun(self.pool, size)
        if not self.client.snapshot_resource_exists(volume_name):
            self.client.create_snapshot_resource(volume_name, raids, size)
            try:
                self.client.enable_snapshot_resource_autoexpand(volume_name)
            except exception.VolumeBackendAPIException:
                LOG.warning('========== Enable snapshot resource auto '
                            'expand for volume: %(volume_name)s error',
                            {'volume_name': volume_name})

        if not self.client.snapshot_enabled(volume_name):
            try:
                self.client.enable_snapshot(volume_name)
            except exception.VolumeBackendAPIException:
                with excutils.save_and_reraise_exception():
                    self.client.delete_snapshot_resource(volume_name)

        try:
            self.client.create_snapshot_point(volume_name, snapshot_name)
            pointid = self.client.get_snapshot_pointid(volume_name,
                                                       snapshot_name)
        except exception.VolumeBackendAPIException:
            with ignored(Exception):
                self.client.disable_snapshot(volume_name)
                self.client.delete_snapshot_resource(volume_name)
            raise

        return int(pointid)

    @synchronized(lock_name)
    @record_request_id
    @volume_utils.trace
    def create_snapshot(self, snapshot):
        """Create a snapshot."""
        volume = snapshot['volume']

        snapshot_name = self._snapshot_name(snapshot['name'])
        volume_name = self._volume_name(volume)

        pointid = self._create_snapshot(snapshot_name,
                                        volume_name,
                                        volume['size'])
        return {'provider_location': 'pointid: %s' % pointid}

    def _delete_snapshot(self, snapshot_name, volume_name, pointid):
        if self.client.snapshot_point_exists(volume_name, pointid):
            self.client.delete_snapshot_point(volume_name, pointid)

        with ignored(Exception):
            n = self.client.get_snapshot_point_num(volume_name)
            if n != 0:
                return
            with ignored(Exception):
                self.client.disable_snapshot(volume_name)
                if not (self.client.dalun_exists(volume_name) or
                        self.client.replication_enabled(volume_name)):
                    self.client.delete_snapshot_resource(volume_name)

    @synchronized(lock_name)
    @record_request_id
    @volume_utils.trace
    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""
        volume = snapshot['volume']
        provider = snapshot['provider_location']
        if not provider:
            return

        m = re.findall(r'pointid: (\d+)', provider)
        if m is None:
            return

        snapshot_name = self._snapshot_name(snapshot['id'])
        volume_name = self._volume_name(volume)
        self._delete_snapshot(snapshot_name, volume_name, m[0])

    def _initialize_connection(self, name, host, wwns):
        raise NotImplementedError

    def _terminate_connection(self, name, host, wwns):
        raise NotImplementedError

    def _create_volume_from_snapshot(self, vol_name, vol_size,
                                     vol_params, snp_name, pointid,
                                     snp_vol_name, snp_vol_size):
        self._create_volume(vol_name, vol_size, vol_params)

        try:
            self.client.create_snapshot_view(snp_name,
                                             snp_vol_name,
                                             pointid)
        except Exception:
            self._delete_volume(vol_name)
            raise exception.VolumeBackendAPIException(
                _('Create snapshot view failed.'))
        try:
            self.client.copy_volume_from_view(vol_name, snp_name)

            while not self.client.snapshot_copy_task_completed(vol_name):
                time.sleep(2)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.client.delete_snapshot_view(snp_name)
                self._delete_volume(vol_name)
        else:
            self.client.delete_snapshot_view(snp_name)

        lun_uuid = self.client.get_lun_uuid(vol_name)
        return {'provider_location': 'macrosan uuid:%s' % lun_uuid}

    @synchronized(lock_name)
    @record_request_id
    @volume_utils.trace
    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot."""
        snapshot_volume = snapshot['volume']
        provider = snapshot['provider_location']
        m = re.findall(r'pointid: (\d+)', provider)
        pointid = int(m[0])

        vol_name = self._volume_name(volume)
        snp_name = self._snapshot_name(snapshot['id'])
        snp_vol_name = self._volume_name(snapshot_volume)

        params = self._parse_volume_params(volume)
        self._check_volume_params(params)

        return self._create_volume_from_snapshot(vol_name,
                                                 volume['size'],
                                                 params,
                                                 snp_name,
                                                 pointid,
                                                 snp_vol_name,
                                                 snapshot['volume_size'])

    def _create_cloned_volume(self, vol_name, vol_size, vol_params,
                              src_vol_name, src_vol_size, snp_name):
        pointid = self._create_snapshot(snp_name,
                                        src_vol_name,
                                        src_vol_size)

        try:
            return self._create_volume_from_snapshot(vol_name,
                                                     vol_size,
                                                     vol_params,
                                                     snp_name,
                                                     pointid,
                                                     src_vol_name,
                                                     src_vol_size)
        finally:
            self._delete_snapshot(snp_name, src_vol_name, pointid)

    @record_request_id
    @volume_utils.trace
    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume."""
        vol_name = volume['id']
        src_vol_name = self._volume_name(src_vref)
        snapshotid =\
            src_vref['id'][:12] + timeutils.utcnow().strftime('%Y%m%d%H%M%S%f')
        snp_name = self._snapshot_name(snapshotid)

        params = self._parse_volume_params(volume)
        self._check_volume_params(params)

        return self._create_cloned_volume(vol_name, volume['size'], params,
                                          src_vol_name, src_vref['size'],
                                          snp_name)

    def _extend_volume(self, name, moresize, params):
        if params['replication_enabled']:
            raise Exception(
                'Volume %s has replication enabled, cannot extend' % name)

        if params['sdas']:
            self.client.suspend_dalun(name)

            raids = self.client.get_raid_list_to_create_lun(self.pool,
                                                            moresize)
            self.client.extend_lun(name, raids, moresize)

            raids = self.sdas_client.get_raid_list_to_create_lun(self.pool,
                                                                 moresize)
            self.sdas_client.extend_lun(name, raids, moresize)

            self.client.resume_dalun(name)
        else:
            raids = self.client.get_raid_list_to_create_lun(self.pool,
                                                            moresize)
            self.client.extend_lun(name, raids, moresize)

    @synchronized(lock_name)
    @record_request_id
    @volume_utils.trace
    def extend_volume(self, volume, new_size):
        """Extend a volume."""
        name = self._volume_name(volume)
        moresize = self._size_str_to_int(new_size - int(volume['size']))
        params = self._parse_volume_params(volume)
        self._extend_volume(name, moresize, params)

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a volume."""
        pass

    def create_export(self, context, volume, connector):
        """Export the volume."""
        pass

    def remove_export(self, context, volume):
        """Remove an export for a volume."""
        pass

    @record_request_id
    def _update_volume_stats(self):
        data = {}
        pool = {}

        total, free, thin_unalloced = self.client.get_pool_cap(self.pool)
        pool['location_info'] = self.device_uuid
        pool['pool_name'] = self.pool
        pool['total_capacity_gb'] = total
        pool['free_capacity_gb'] = free + thin_unalloced
        pool['reserved_percentage'] = self.configuration.safe_get(
            'reserved_percentage')
        pool['max_over_subscription_ratio'] = self.configuration.safe_get(
            'max_over_subscription_ratio')
        pool['QoS_support'] = True
        pool['multiattach'] = True
        pool['lun_mode'] = True
        pool['replication_mode'] = []

        if self.replica_client:
            pool['replication_enabled'] = 'True'
            pool['replication_mode'].append('async')

        if self.sdas_client:
            pool['replication_enabled'] = 'True'
            pool['sdas'] = 'True'
            pool['replication_mode'].append('sync')

        if len(pool['replication_mode']) == 0:
            del pool['replication_mode']

        data['pools'] = [pool]
        data["volume_backend_name"] = self.volume_backend_name
        data["vendor_name"] = 'MacroSAN'
        data["driver_version"] = version
        data["storage_protocol"] = self.storage_protocol

        self._stats = data

    @record_request_id
    @volume_utils.trace
    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status=None):
        """Return model update for migrated volume."""
        original_name = self._volume_name(volume)
        cur_name = self._volume_name(new_volume)

        if self.client.lun_exists(original_name):
            self.client.backup_lun_name_to_rename_file(cur_name, original_name)
        else:
            if original_volume_status == 'available':
                try:
                    self.client.rename_lun(cur_name, original_name)
                except Exception:
                    LOG.warning('========== failed to rename '
                                '%(cur_name)s to %(original_name)s',
                                {'cur_name': cur_name,
                                 'original_name': original_name})

        name_id = new_volume['_name_id'] or new_volume['id']
        return {'_name_id': name_id,
                'provider_location': new_volume['provider_location']}

    @synchronized(lock_name)
    @record_request_id
    @volume_utils.trace
    def initialize_connection_snapshot(self, snapshot, connector, **kwargs):
        volume = snapshot['volume']
        provider = snapshot['provider_location']
        m = re.findall(r'pointid: (\d+)', provider)

        pointid = m[0]
        snp_name = self._snapshot_name(snapshot['id'])
        snp_vol_name = self._volume_name(volume)

        self.client.create_snapshot_view(snp_name, snp_vol_name, pointid)

        try:
            conn = self._initialize_connection_snapshot(snp_name, connector)
            conn['data']['volume_id'] = snapshot['id']
            return conn
        except Exception:
            with excutils.save_and_reraise_exception():
                self.client.delete_snapshot_view(snp_name)

    def _initialize_connection_snapshot(self, snp_name, connector):
        raise NotImplementedError

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        snp_name = self._snapshot_name(snapshot['id'])
        self._terminate_connection_snapshot(snp_name, connector)
        self.client.delete_snapshot_view(snp_name)

    def _terminate_connection_snapshot(self, snp_name, connector):
        raise NotImplementedError

    @record_request_id
    def manage_existing_get_size(self, volume, external_ref):
        __, info, __ = self._get_existing_lun_info(external_ref)
        size = int(math.ceil(info['size']))
        return size

    @synchronized(lock_name)
    @record_request_id
    @volume_utils.trace
    def manage_existing(self, volume, external_ref):
        vol_params = self._parse_volume_params(volume)
        self._check_volume_params(vol_params)
        if vol_params['qos-strategy']:
            raise exception.VolumeBackendAPIException(
                data=_('Import qos-strategy not supported'))

        pool = volume_utils.extract_host(volume.host, 'pool')
        name, info, params = self._get_existing_lun_info(external_ref)
        if pool != info['pool']:
            msg = _("LUN %(name)s does not belong to the pool: "
                    "%(pool)s."), {'name': name, 'pool': pool}
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref, reason=msg)

        if params['sdas'] and params['replication_enabled']:
            msg = _('LUN %(name)s sdas and replication '
                    'enabled at same time'), {'name': name}
            raise exception.VolumeBackendAPIException(data=msg)

        if replication_synced(vol_params) and params['sdas']:
            params.update({'sdas': False,
                           'replication_mode': 'sync',
                           'replication_enabled': True})

        def notequal(attr):
            return vol_params[attr] != params[attr]

        if (notequal('replication_enabled') or notequal('replication_mode') or
                notequal('sdas') or notequal('lun_mode')):
            msg = _("Volume type: %(vol_params)s doesn't equal "
                    "to existing lun: "
                    "%(params)s"), {'vol_params': vol_params, 'params': params}
            raise exception.VolumeBackendAPIException(data=msg)

        rmt_client = None
        if params['sdas']:
            rmt_client = self.sdas_client
        elif params['replication_enabled']:
            rmt_client = self.replica_client

        snp_res_name = self.client.get_snapshot_resource_name(name)
        self.client.rename_lun(name, volume['name'])
        if snp_res_name:
            self.client.rename_lun(snp_res_name, 'SR-%s' % volume['id'])

        if params['sdas'] or params['replication_enabled']:
            snp_res_name = rmt_client.get_snapshot_resource_name(name)
            rmt_client.rename_lun(name, volume['name'])
            if snp_res_name:
                rmt_client.rename_lun(snp_res_name, 'SR-%s' % volume['id'])

        lun_uuid = self.client.get_lun_uuid(volume['name'])
        return {'provider_location': 'macrosan uuid:%s' % lun_uuid}

    def _get_existing_lun_info(self, external_ref):
        name = external_ref.get('source-name')
        if not name:
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref,
                reason=_('No source-name to get existing lun'))

        info = self.client.get_lun_base_info(name)

        params = {
            'qos-strategy': '',
            'replication_enabled': False,
            'replication_mode': 'async',
            'sdas': False,
            'lun_mode': False
        }

        sdas = self.client.dalun_exists(name)
        rep = self.client.replication_enabled(name)
        params['replication_enabled'] = rep
        params['sdas'] = sdas
        if info['lun_mode'] == 'thin':
            info['lun_mode'] = True
        else:
            info['lun_mode'] = False
        params['lun_mode'] = info['lun_mode']

        return name, info, params

    def unmanage(self, volume):
        pass

    @synchronized(lock_name)
    @record_request_id
    @volume_utils.trace
    def manage_existing_snapshot(self, snapshot, existing_ref):
        volume = snapshot['volume']
        src_name = self._get_existing_snapname(existing_ref).lstrip('_')
        src_name = self._snapshot_name(src_name)
        pointid = self.client.get_snapshot_pointid(volume['name'], src_name)
        snap_name = self._snapshot_name(snapshot['id'])

        self.client.rename_snapshot_point(volume['name'], pointid, snap_name)
        return {'provider_location': 'pointid: %s' % pointid}

    @record_request_id
    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        volume = snapshot['volume']
        return volume['size']

    def _get_existing_snapname(self, external_ref):
        name = external_ref.get('source-name')
        if not name:
            raise exception.ManageExistingInvalidReference(
                existing_ref=external_ref,
                reason=_('No source-name to get existing snap'))
        return name

    def unmanage_snapshot(self, snapshot):
        pass

    def migration_valid(self, volume, host):
        if volume.volume_attachment:
            return False

        pool_name = host['capabilities'].get('pool_name', '')
        if pool_name == '':
            return False

        device_uuid = host['capabilities']['location_info']
        if device_uuid != self.device_uuid:
            return False

        params = self._parse_volume_params(volume)
        if params['sdas'] or params['replication_enabled']:
            return False

        return True

    @synchronized(lock_name)
    @record_request_id
    @volume_utils.trace
    def migrate_volume(self, ctxt, volume, host):
        if not self.migration_valid(volume, host):
            return False, None

        size = self._size_str_to_int(volume['size'])
        params = self._parse_volume_params(volume)
        name = str(uuid.uuid4())
        src_name = self._volume_name(volume)
        owner = self.client.get_lun_sp(src_name)
        pool = host['capabilities'].get('pool_name', self.pool)

        LOG.info('Migrating volume: %(volume)s, '
                 'host: %(host)s, '
                 'backend: %(volume_backend_name)s',
                 {'volume': src_name,
                  'host': host,
                  'volume_backend_name': self.volume_backend_name})
        self._create_volume(name, size, params, owner, pool)

        res_sz = int(max(int(size) * self.snapshot_resource_ratio, 1))
        src_snp_res_exists = self.client.snapshot_resource_exists(src_name)
        if not src_snp_res_exists:
            raids = self.client.get_raid_list_to_create_lun(self.pool, res_sz)
            self.client.create_snapshot_resource(src_name, raids, res_sz)

        snp_res_exists = self.client.snapshot_resource_exists(name)
        if not snp_res_exists:
            raids = self.client.get_raid_list_to_create_lun(pool, res_sz)
            self.client.create_snapshot_resource(name, raids, res_sz)

        self.client.start_localclone_lun(src_name, name)
        while not self.client.localclone_completed(name):
            time.sleep(2)
        self.client.stop_localclone_lun(name)

        if not snp_res_exists:
            self.client.delete_snapshot_resource(name)
        if not src_snp_res_exists:
            self.client.delete_snapshot_resource(src_name)

        self._delete_volume(src_name, params)
        self.client.rename_lun(name, src_name)

        lun_uuid = self.client.get_lun_uuid(src_name)
        return True, {'provider_location': 'macrosan uuid:%s' % lun_uuid}

    def force_terminate_connection(self, name, force_connected=False):
        it_list = self.client.get_lun_it(name)
        it_list = [it for it in it_list
                   if (force_connected or not it['connected'])]
        if len(it_list) > 0:
            for it in it_list:
                self.client.unmap_lun_to_it(name,
                                            it['initiator'],
                                            it['port'])


@interface.volumedriver
class MacroSANISCSIDriver(MacroSANBaseDriver, driver.ISCSIDriver):
    """ISCSI driver for MacroSan storage arrays.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver
        1.0.1 - Adjust some log level and text prompts; Remove some useless
        functions; Add Cinder trace decorator. #1837920
    """
    VERSION = "1.0.1"

    def __init__(self, *args, **kwargs):
        """Initialize the driver."""
        super(MacroSANISCSIDriver, self).__init__(*args, **kwargs)
        self.storage_protocol = 'iSCSI'

    def _do_setup(self):
        ports = self.client.get_iscsi_ports()
        for port in ports:
            if port['port_name'] == '' and port['ip'] != '0':
                self.client.create_target(port['port'], type='iscsi')

        if self.sdas_client:
            ports = self.sdas_client.get_iscsi_ports()
            for port in ports:
                if port['port_name'] == '' and port['ip'] != '0':
                    self.sdas_client.create_target(port['port'], type='iscsi')

    def _get_iscsi_ports(self, dev_client, host):
        ha_state = dev_client.get_ha_state()

        if host in self.client_info:
            iscsi_sp1 = self.client_info[host]['sp1_port']
            iscsi_sp2 = self.client_info[host]['sp2_port']
        else:
            iscsi_sp1 = self.client_info['default']['sp1_port']
            iscsi_sp2 = self.client_info['default']['sp2_port']
        ports = []
        if ha_state['sp1'] in ['single', 'double', 'idle']:
            ports.extend(iscsi_sp1.split(','))

        if ha_state['sp2'] in ['single', 'double', 'idle']:
            ports.extend(iscsi_sp2.split(','))

        all_ports = {p['port']: p for p in dev_client.get_iscsi_ports()}

        return [all_ports[p] for p in ports]

    def _map_initr_tgt(self, dev_client, itl_client_name, initr, ports):
        if not dev_client.get_client(itl_client_name):
            dev_client.create_client(itl_client_name)

        if not dev_client.initiator_exists(initr):
            dev_client.create_initiator(initr, itl_client_name, type='iscsi')

        if not dev_client.is_initiator_mapped_to_client(initr,
                                                        itl_client_name):
            dev_client.map_initiator_to_client(initr, itl_client_name)

        for p in ports:
            port_name = p['port_name']
            dev_client.map_target_to_initiator(port_name, initr)

    def _unmap_itl(self, dev_client, itl_client_name,
                   wwns, ports, volume_name):
        wwn = wwns[0]
        for p in ports:
            port_name = p['port_name']
            dev_client.unmap_lun_to_it(volume_name, wwn, port_name)

    def _map_itl(self, dev_client, wwn, ports, volume_name, hint_lun_id):
        lun_id = hint_lun_id
        exists = False
        for p in ports:
            port_name = p['port_name']
            exists = dev_client.map_lun_to_it(volume_name, wwn, port_name,
                                              hint_lun_id)

            if exists and lun_id == hint_lun_id:
                lun_id = self.client.get_lun_id(wwn, port_name, volume_name)

        return lun_id

    def _get_unused_lun_id(self, wwn, dev_client, ports,
                           sdas_client, sdas_ports):
        id_list = set(range(0, 511))
        for p in ports:
            port_name = p['port_name']
            tmp_list = dev_client.get_it_unused_id_list('iscsi', wwn,
                                                        port_name)
            id_list = id_list.intersection(tmp_list)

        for p in sdas_ports:
            port_name = p['port_name']
            tmp_list = sdas_client.get_it_unused_id_list('iscsi', wwn,
                                                         port_name)
            id_list = id_list.intersection(tmp_list)

        return id_list.pop()

    def _initialize_connection(self, name, vol_params, host, wwns):
        client_name = self._get_client_name(host)
        wwn = wwns[0]
        LOG.debug('initialize_connection, initiator: %(wwpns)s,'
                  'volume name: %(volume)s.',
                  {'wwpns': wwns, 'volume': name})

        ports = self._get_iscsi_ports(self.client, host)
        self._map_initr_tgt(self.client, client_name, wwn, ports)

        if vol_params['sdas']:
            sdas_ports = self._get_iscsi_ports(self.sdas_client, host)
            self._map_initr_tgt(self.sdas_client, client_name, wwn, sdas_ports)
            lun_id = self._get_unused_lun_id(wwn, self.client, ports,
                                             self.sdas_client, sdas_ports)

            self._map_itl(self.sdas_client, wwn, sdas_ports, name, lun_id)

            lun_id = self._map_itl(self.client, wwn, ports, name, lun_id)

            ports = ports + sdas_ports
        else:
            lun_id = self._get_unused_lun_id(wwn, self.client, ports, None, {})
            lun_id = self._map_itl(self.client, wwn, ports, name, lun_id)

        properties = {'target_discovered': False,
                      'target_portal': '%s:3260' % ports[0]['ip'],
                      'target_iqn': ports[0]['target'],
                      'target_lun': lun_id,
                      'target_iqns': [p['target'] for p in ports],
                      'target_portals': ['%s:3260' % p['ip'] for p in ports],
                      'target_luns': [lun_id] * len(ports)}

        LOG.info('initialize_connection, iSCSI properties: %(properties)s',
                 {'properties': properties})
        return {'driver_volume_type': 'iscsi', 'data': properties}

    @synchronized(lock_name)
    @record_request_id
    @volume_utils.trace
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""

        name = self._volume_name(volume)
        params = self._parse_volume_params(volume)
        conn = self._initialize_connection(name, params, connector['host'],
                                           [connector['initiator']])
        conn['data']['volume_id'] = volume['id']
        return conn

    def _unmap_initr_tgt(self, dev_client, itl_client_name, wwn):
        for p in dev_client.get_iscsi_ports():
            port_name = p['port_name']
            if dev_client.it_exists(wwn, port_name):
                dev_client.unmap_target_from_initiator(port_name, wwn)

        if dev_client.initiator_exists(wwn):
            dev_client.unmap_initiator_from_client(wwn, itl_client_name)
            dev_client.delete_initiator(wwn)

    def _terminate_connection(self, name, volume_params, host, wwns):
        client_name = self._get_client_name(host)
        ports = self._get_iscsi_ports(self.client, host)

        self._unmap_itl(self.client, client_name, wwns, ports, name)
        if volume_params['sdas']:
            self._unmap_itl(self.sdas_client, client_name, wwns, ports, name)

        data = dict()
        data['ports'] = ports
        data['client'] = client_name
        return {'driver_volume_type': 'iSCSI', 'data': data}

    @synchronized(lock_name)
    @record_request_id
    @volume_utils.trace
    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""

        name = self._volume_name(volume)
        conn = None
        if not connector:
            self.force_terminate_connection(name, True)
        else:
            params = self._parse_volume_params(volume)
            conn = self._terminate_connection(name, params, connector['host'],
                                              [connector['initiator']])
        return conn

    def _initialize_connection_snapshot(self, snp_name, connector):
        return self._initialize_connection(snp_name, None, connector['host'],
                                           [connector['initiator']])

    def _terminate_connection_snapshot(self, snp_name, connector):
        return self._terminate_connection(snp_name, None, connector['host'],
                                          [connector['initiator']])


@interface.volumedriver
class MacroSANFCDriver(MacroSANBaseDriver, driver.FibreChannelDriver):
    """FC driver for MacroSan storage arrays.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver
        1.0.1 - Adjust some log level and text prompts; Remove some useless
        functions; Add Cinder trace decorator. #1837920
    """
    VERSION = "1.0.1"

    def __init__(self, *args, **kwargs):
        """Initialize the driver."""
        super(MacroSANFCDriver, self).__init__(*args, **kwargs)
        self.storage_protocol = 'FC'
        self.fcsan_lookup_service = None
        self.use_sp_port_nr = self.configuration.macrosan_fc_use_sp_port_nr
        self.keep_mapped_ports = \
            self.configuration.macrosan_fc_keep_mapped_ports

    def _do_setup(self):
        self.fcsan_lookup_service = fczm_utils.create_lookup_service()

        ports = self.client.get_fc_ports()
        for port in ports:
            if port['port_name'] == '':
                self.client.create_target(port['port'])

        if self.sdas_client:
            ports = self.sdas_client.get_fc_ports()
            for port in ports:
                if port['port_name'] == '':
                    self.sdas_client.create_target(port['port'])

    def _strip_wwn_colon(self, wwn_str):
        return wwn_str.replace(':', '')

    def _format_wwn_with_colon(self, wwn_str):
        wwn_str = wwn_str.replace(":", "")
        return (':'.join([wwn_str[i:i + 2]
                for i in range(0, len(wwn_str), 2)])).lower()

    def _select_fc_ports(self, ports_in_storage, ports_in_fabric):
        selected = []
        for sp in [1, 2]:
            n = 0
            for p in ports_in_storage:
                if (p['sp'] == sp
                        and p['online'] == 1 and p['wwn'] in ports_in_fabric):
                    selected.append({'port_name': p['port_name'],
                                     'wwn': p['wwn']})
                    n += 1
                    if n >= self.use_sp_port_nr:
                        break
        return selected

    def _get_initr_port_map(self, dev_client, wwns):
        initr_port_map = {}
        ports_in_storage = dev_client.get_fc_ports()
        if self.fcsan_lookup_service is not None:
            mapping = (self.fcsan_lookup_service
                           .get_device_mapping_from_network(
                               wwns, [p['wwn'] for p in ports_in_storage]))

            for fabric in mapping:
                wwns = mapping[fabric]['target_port_wwn_list']
                mapping[fabric]['target_port_wwn_list'] = (
                    [self._format_wwn_with_colon(wwn) for wwn in wwns])
                wwns = mapping[fabric]['initiator_port_wwn_list']
                mapping[fabric]['initiator_port_wwn_list'] = (
                    [self._format_wwn_with_colon(wwn) for wwn in wwns])

            for fabric in mapping:
                ports_in_fabric = mapping[fabric]['target_port_wwn_list']
                selected_ports = self._select_fc_ports(ports_in_storage,
                                                       ports_in_fabric)

                for initr in mapping[fabric]['initiator_port_wwn_list']:
                    initr_port_map[initr] = selected_ports
        else:
            initr_port_map = {}
            for wwn in wwns:
                for port in ports_in_storage:
                    if port['initr'] == wwn:
                        initr_port_map[wwn] = [port]
                        break

        return initr_port_map

    def _map_initr_tgt_do(self, dev_client, itl_client_name,
                          initr_port_map, mapped_ports):
        for wwn in initr_port_map:
            if wwn in mapped_ports:
                continue

            if not dev_client.initiator_exists(wwn):
                dev_client.create_initiator(wwn, wwn)

            if not dev_client.is_initiator_mapped_to_client(wwn,
                                                            itl_client_name):
                dev_client.map_initiator_to_client(wwn, itl_client_name)

            for p in initr_port_map[wwn]:
                port_name = p['port_name']
                dev_client.map_target_to_initiator(port_name, wwn)

    def _unmap_initr_tgt(self, dev_client, client_name, mapped_ports):
        for wwn in mapped_ports:
            for p in mapped_ports[wwn]:
                port_name = p['port_name']
                if dev_client.it_exists(wwn, port_name):
                    dev_client.unmap_target_from_initiator(port_name, wwn)

            if dev_client.initiator_exists(wwn):
                dev_client.unmap_initiator_from_client(wwn, client_name)
                dev_client.delete_initiator(wwn)

    def _map_initr_tgt(self, dev_client, itl_client_name, wwns):
        if not dev_client.get_client(itl_client_name):
            dev_client.create_client(itl_client_name)

        initr_port_map = {}
        mapped_ports = dev_client.get_fc_initr_mapped_ports(wwns)
        has_port_not_mapped = not all(wwn in mapped_ports for wwn in wwns)
        if has_port_not_mapped:
            initr_port_map = self._get_initr_port_map(dev_client, wwns)

        initr_port_map.update(mapped_ports)

        if has_port_not_mapped:
            self._map_initr_tgt_do(dev_client, itl_client_name,
                                   initr_port_map, mapped_ports)
        return has_port_not_mapped, initr_port_map

    def _map_itl(self, dev_client, initr_port_map, volume_name, hint_lun_id):
        lun_id = hint_lun_id
        exists = False
        for wwn in initr_port_map:
            for p in initr_port_map[wwn]:
                port_name = p['port_name']
                exists = dev_client.map_lun_to_it(volume_name, wwn,
                                                  port_name, lun_id)

                if exists and lun_id == hint_lun_id:
                    lun_id = dev_client.get_lun_id(wwn, port_name, volume_name)
        return lun_id

    def _get_unused_lun_id(self, dev_client, initr_port_map,
                           sdas_client, sdas_initr_port_map):
        id_list = set(range(0, 511))
        for wwn in initr_port_map:
            for p in initr_port_map[wwn]:
                port_name = p['port_name']
                tmp_list = dev_client.get_it_unused_id_list('fc', wwn,
                                                            port_name)
                id_list = id_list.intersection(tmp_list)

        for wwn in sdas_initr_port_map:
            for p in sdas_initr_port_map[wwn]:
                port_name = p['port_name']
                tmp_list = sdas_client.get_it_unused_id_list('fc', wwn,
                                                             port_name)
                id_list = id_list.intersection(tmp_list)

        return id_list.pop()

    def _initialize_connection(self, name, vol_params, host, wwns):
        client_name = self._get_client_name(host)

        LOG.info('initialize_connection, initiator: %(wwpns)s, '
                 'volume name: %(volume)s.',
                 {'wwpns': wwns, 'volume': name})

        has_port_not_mapped, initr_port_map = (
            self._map_initr_tgt(self.client, client_name, wwns))
        LOG.debug('initr_port_map: %(initr_port_map)s',
                  {'initr_port_map': initr_port_map})

        if vol_params and vol_params['sdas']:
            sdas_has_port_not_mapped, sdas_initr_port_map = (
                self._map_initr_tgt(self.sdas_client, client_name, wwns))
            lun_id = self._get_unused_lun_id(self.client, initr_port_map,
                                             self.sdas_client,
                                             sdas_initr_port_map)
            LOG.debug('sdas_initr_port_map: %(sdas_initr_port_map)s',
                      {'sdas_initr_port_map': sdas_initr_port_map})
            self._map_itl(self.sdas_client, sdas_initr_port_map, name, lun_id)

            lun_id = self._map_itl(self.client, initr_port_map, name, lun_id)
            for initr, ports in sdas_initr_port_map.items():
                if len(ports):
                    initr_port_map[initr].extend(ports)

            has_port_not_mapped = (has_port_not_mapped or
                                   sdas_has_port_not_mapped)
        else:
            lun_id = self._get_unused_lun_id(self.client, initr_port_map,
                                             None, {})
            lun_id = self._map_itl(self.client, initr_port_map, name, lun_id)

        tgt_wwns = list(set(self._strip_wwn_colon(p['wwn'])
                        for wwn in initr_port_map
                        for p in initr_port_map[wwn]))
        tgt_wwns.sort()

        properties = {'target_lun': lun_id,
                      'target_discovered': True,
                      'target_wwn': tgt_wwns}
        if has_port_not_mapped and self.fcsan_lookup_service is not None:
            initr_tgt_map = {}
            for initr, ports in initr_port_map.items():
                initr = self._strip_wwn_colon(initr)
                initr_tgt_map[initr] = (
                    [self._strip_wwn_colon(p['wwn']) for p in ports])

            properties['initiator_target_map'] = initr_tgt_map

        LOG.info('initialize_connection, FC properties: %(properties)s',
                 {'properties': properties})
        return {'driver_volume_type': 'fibre_channel', 'data': properties}

    @synchronized(lock_name)
    @record_request_id
    @volume_utils.trace
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""

        name = self._volume_name(volume)
        params = self._parse_volume_params(volume)
        wwns = [self._format_wwn_with_colon(wwns)
                for wwns in connector['wwnns']]
        conn = self._initialize_connection(name, params,
                                           connector['host'], wwns)
        conn['data']['volume_id'] = volume['id']
        fczm_utils.add_fc_zone(conn)
        return conn

    def _unmap_itl(self, dev_client, name, itl_client_name, wwns):
        mapped_ports = dev_client.get_fc_initr_mapped_ports(wwns)
        if len(mapped_ports) == 0:
            return [], {}

        for wwn, ports in mapped_ports.items():
            for p in ports:
                port_name = p['port_name']
                dev_client.unmap_lun_to_it(name, wwn, port_name)

        ports, initr_tgt_map = [], {}
        if (not self.keep_mapped_ports and
                not dev_client.has_initiators_mapped_any_lun(wwns)):
            mapped_ports = dev_client.get_fc_initr_mapped_ports(wwns)
            initr_tgt_map = {self._strip_wwn_colon(wwn):
                             [self._strip_wwn_colon(p['wwn'])
                             for p in mapped_ports[wwn]] for wwn in wwns}
            ports = list(set(self._strip_wwn_colon(p['wwn'])
                         for ports in mapped_ports.values()
                         for p in ports))
            self._unmap_initr_tgt(dev_client, itl_client_name, mapped_ports)
            if self.fcsan_lookup_service is None:
                initr_tgt_map = {}

        return ports, initr_tgt_map

    def _terminate_connection(self, name, vol_params, host, wwns):
        client_name = self._get_client_name(host)
        ports, initr_tgt_map = self._unmap_itl(self.client, name,
                                               client_name, wwns)
        if vol_params and vol_params['sdas']:
            sdas_ports, sdas_initr_tgt_map = (
                self._unmap_itl(self.sdas_client, name,
                                client_name, wwns))
            ports.extend(sdas_ports)
            for initr, tgt_wwns in sdas_initr_tgt_map.items():
                if len(tgt_wwns):
                    initr_tgt_map[initr].extend(tgt_wwns)

        data = {}
        if ports:
            data['target_wwn'] = ports
        if initr_tgt_map:
            data['initiator_target_map'] = initr_tgt_map
        LOG.info('terminate_connection, data: %(data)s', {'data': data})
        return {'driver_volume_type': 'fibre_channel', 'data': data}

    @synchronized(lock_name)
    @record_request_id
    @volume_utils.trace
    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""

        name = self._volume_name(volume)
        conn = None
        if not connector:
            self.force_terminate_connection(name, True)
            conn = {'driver_volume_type': 'fibre_channel', 'data': {}}
        else:
            params = self._parse_volume_params(volume)
            wwns = [self._format_wwn_with_colon(wwns)
                    for wwns in connector['wwpns']]
            attachments = volume.volume_attachment
            hostnum = 0
            for i in attachments:
                if connector['host'] == i['attached_host']:
                    hostnum += 1
            if hostnum > 1:
                pass
            else:
                conn = self._terminate_connection(name, params,
                                                  connector['host'], wwns)
        fczm_utils.remove_fc_zone(conn)
        return conn

    def _initialize_connection_snapshot(self, snp_name, connector):
        wwns = [self._format_wwn_with_colon(wwns)
                for wwns in connector['wwpns']]
        return self._initialize_connection(snp_name, None, connector['host'],
                                           wwns)

    def _terminate_connection_snapshot(self, snp_name, connector):
        wwns = [self._format_wwn_with_colon(wwns)
                for wwns in connector['wwpns']]
        return self._terminate_connection(snp_name, None, connector['host'],
                                          wwns)
