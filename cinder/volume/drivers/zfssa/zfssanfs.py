# Copyright (c) 2014, Oracle and/or its affiliates. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""
ZFS Storage Appliance NFS Cinder Volume Driver
"""
import base64
import datetime as dt
import errno

from oslo_config import cfg
from oslo_log import log
from oslo_utils import excutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LE, _LI
from cinder.volume.drivers import nfs
from cinder.volume.drivers.san import san
from cinder.volume.drivers.zfssa import zfssarest


ZFSSA_OPTS = [
    cfg.StrOpt('zfssa_data_ip',
               help='Data path IP address'),
    cfg.StrOpt('zfssa_https_port', default='443',
               help='HTTPS port number'),
    cfg.StrOpt('zfssa_nfs_mount_options', default='',
               help='Options to be passed while mounting share over nfs'),
    cfg.StrOpt('zfssa_nfs_pool', default='',
               help='Storage pool name.'),
    cfg.StrOpt('zfssa_nfs_project', default='NFSProject',
               help='Project name.'),
    cfg.StrOpt('zfssa_nfs_share', default='nfs_share',
               help='Share name.'),
    cfg.StrOpt('zfssa_nfs_share_compression', default='off',
               choices=['off', 'lzjb', 'gzip-2', 'gzip', 'gzip-9'],
               help='Data compression.'),
    cfg.StrOpt('zfssa_nfs_share_logbias', default='latency',
               choices=['latency', 'throughput'],
               help='Synchronous write bias-latency, throughput.'),
    cfg.IntOpt('zfssa_rest_timeout',
               help='REST connection timeout. (seconds)')
]

LOG = log.getLogger(__name__)

CONF = cfg.CONF
CONF.register_opts(ZFSSA_OPTS)


def factory_zfssa():
    return zfssarest.ZFSSANfsApi()


class ZFSSANFSDriver(nfs.NfsDriver):
    VERSION = '1.0.0'
    volume_backend_name = 'ZFSSA_NFS'
    protocol = driver_prefix = driver_volume_type = 'nfs'

    def __init__(self, *args, **kwargs):
        super(ZFSSANFSDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(ZFSSA_OPTS)
        self.configuration.append_config_values(san.san_opts)
        self.zfssa = None
        self._stats = None

    def do_setup(self, context):
        if not self.configuration.nfs_oversub_ratio > 0:
            msg = _("NFS config 'nfs_oversub_ratio' invalid. Must be > 0: "
                    "%s") % self.configuration.nfs_oversub_ratio
            LOG.error(msg)
            raise exception.NfsException(msg)

        if ((not self.configuration.nfs_used_ratio > 0) and
                (self.configuration.nfs_used_ratio <= 1)):
            msg = _("NFS config 'nfs_used_ratio' invalid. Must be > 0 "
                    "and <= 1.0: %s") % self.configuration.nfs_used_ratio
            LOG.error(msg)
            raise exception.NfsException(msg)

        package = 'mount.nfs'
        try:
            self._execute(package, check_exit_code=False, run_as_root=True)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                msg = _('%s is not installed') % package
                raise exception.NfsException(msg)
            else:
                raise exc

        lcfg = self.configuration
        LOG.info(_LI('Connecting to host: %s.'), lcfg.san_ip)

        host = lcfg.san_ip
        user = lcfg.san_login
        password = lcfg.san_password
        https_port = lcfg.zfssa_https_port

        credentials = ['san_ip', 'san_login', 'san_password', 'zfssa_data_ip']

        for cred in credentials:
            if not getattr(lcfg, cred, None):
                exception_msg = _('%s not set in cinder.conf') % cred
                LOG.error(exception_msg)
                raise exception.CinderException(exception_msg)

        self.zfssa = factory_zfssa()
        self.zfssa.set_host(host, timeout=lcfg.zfssa_rest_timeout)

        auth_str = base64.encodestring('%s:%s' % (user, password))[:-1]
        self.zfssa.login(auth_str)

        self.zfssa.create_project(lcfg.zfssa_nfs_pool, lcfg.zfssa_nfs_project,
                                  compression=lcfg.zfssa_nfs_share_compression,
                                  logbias=lcfg.zfssa_nfs_share_logbias)

        share_args = {
            'sharedav': 'rw',
            'sharenfs': 'rw',
            'root_permissions': '777',
            'compression': lcfg.zfssa_nfs_share_compression,
            'logbias': lcfg.zfssa_nfs_share_logbias
        }

        self.zfssa.create_share(lcfg.zfssa_nfs_pool, lcfg.zfssa_nfs_project,
                                lcfg.zfssa_nfs_share, share_args)

        share_details = self.zfssa.get_share(lcfg.zfssa_nfs_pool,
                                             lcfg.zfssa_nfs_project,
                                             lcfg.zfssa_nfs_share)

        mountpoint = share_details['mountpoint']

        self.mount_path = lcfg.zfssa_data_ip + ':' + mountpoint
        https_path = 'https://' + lcfg.zfssa_data_ip + ':' + https_port + \
            '/shares' + mountpoint

        LOG.debug('NFS mount path: %s' % self.mount_path)
        LOG.debug('WebDAV path to the share: %s' % https_path)

        self.shares = {}
        mnt_opts = self.configuration.zfssa_nfs_mount_options
        self.shares[self.mount_path] = mnt_opts if len(mnt_opts) > 1 else None

        # Initialize the WebDAV client
        self.zfssa.set_webdav(https_path, auth_str)

        # Edit http service so that WebDAV requests are always authenticated
        args = {'https_port': https_port,
                'require_login': True}

        self.zfssa.modify_service('http', args)
        self.zfssa.enable_service('http')

    def _ensure_shares_mounted(self):
        try:
            self._ensure_share_mounted(self.mount_path)
        except Exception as exc:
            LOG.error(_LE('Exception during mounting %s.') % exc)

        self._mounted_shares = [self.mount_path]
        LOG.debug('Available shares %s' % self._mounted_shares)

    def check_for_setup_error(self):
        """Check that driver can login.

        Check also for properly configured pool, project and share
        Check that the http and nfs services are enabled
        """
        lcfg = self.configuration

        self.zfssa.verify_pool(lcfg.zfssa_nfs_pool)
        self.zfssa.verify_project(lcfg.zfssa_nfs_pool, lcfg.zfssa_nfs_project)
        self.zfssa.verify_share(lcfg.zfssa_nfs_pool, lcfg.zfssa_nfs_project,
                                lcfg.zfssa_nfs_share)
        self.zfssa.verify_service('http')
        self.zfssa.verify_service('nfs')

    def create_snapshot(self, snapshot):
        """Creates a snapshot of a volume."""
        LOG.info(_LI('Creating snapshot: %s'), snapshot['name'])
        lcfg = self.configuration
        snap_name = self._create_snapshot_name()
        self.zfssa.create_snapshot(lcfg.zfssa_nfs_pool, lcfg.zfssa_nfs_project,
                                   lcfg.zfssa_nfs_share, snap_name)

        src_file = snap_name + '/' + snapshot['volume_name']

        try:
            self.zfssa.create_snapshot_of_volume_file(src_file=src_file,
                                                      dst_file=
                                                      snapshot['name'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.debug('Error thrown during snapshot: %s creation' %
                          snapshot['name'])
        finally:
            self.zfssa.delete_snapshot(lcfg.zfssa_nfs_pool,
                                       lcfg.zfssa_nfs_project,
                                       lcfg.zfssa_nfs_share, snap_name)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        LOG.info(_LI('Deleting snapshot: %s'), snapshot['name'])
        self.zfssa.delete_snapshot_of_volume_file(src_file=snapshot['name'])

    def create_volume_from_snapshot(self, volume, snapshot, method='COPY'):
        LOG.info(_LI('Creatng volume from snapshot. volume: %s'),
                 volume['name'])
        LOG.info(_LI('Source Snapshot: %s'), snapshot['name'])

        self._ensure_shares_mounted()
        self.zfssa.create_volume_from_snapshot_file(src_file=snapshot['name'],
                                                    dst_file=volume['name'],
                                                    method=method)

        volume['provider_location'] = self.mount_path

        if volume['size'] != snapshot['volume_size']:
            try:
                self.extend_volume(volume, volume['size'])
            except Exception:
                vol_path = self.local_path(volume)
                exception_msg = (_('Error in extending volume size: '
                                   'Volume: %(volume)s '
                                   'Vol_Size: %(vol_size)d with '
                                   'Snapshot: %(snapshot)s '
                                   'Snap_Size: %(snap_size)d')
                                 % {'volume': volume['name'],
                                    'vol_size': volume['size'],
                                    'snapshot': snapshot['name'],
                                    'snap_size': snapshot['volume_size']})
                with excutils.save_and_reraise_exception():
                    LOG.error(exception_msg)
                    self._execute('rm', '-f', vol_path, run_as_root=True)

        return {'provider_location': volume['provider_location']}

    def create_cloned_volume(self, volume, src_vref):
        """Creates a snapshot and then clones the snapshot into a volume."""
        LOG.info(_LI('new cloned volume: %s'), volume['name'])
        LOG.info(_LI('source volume for cloning: %s'), src_vref['name'])

        snapshot = {'volume_name': src_vref['name'],
                    'volume_id': src_vref['id'],
                    'volume_size': src_vref['size'],
                    'name': self._create_snapshot_name()}

        self.create_snapshot(snapshot)
        return self.create_volume_from_snapshot(volume, snapshot,
                                                method='MOVE')

    def _create_snapshot_name(self):
        """Creates a snapshot name from the date and time."""

        return ('cinder-zfssa-nfs-snapshot-%s' %
                dt.datetime.utcnow().isoformat())

    def _get_share_capacity_info(self):
        """Get available and used capacity info for the NFS share."""
        lcfg = self.configuration
        share_details = self.zfssa.get_share(lcfg.zfssa_nfs_pool,
                                             lcfg.zfssa_nfs_project,
                                             lcfg.zfssa_nfs_share)

        free = share_details['space_available']
        used = share_details['space_total']
        return free, used

    def _update_volume_stats(self):
        """Get volume stats from zfssa"""
        self._ensure_shares_mounted()
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.__class__.__name__
        data['vendor_name'] = 'Oracle'
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = self.protocol

        free, used = self._get_share_capacity_info()
        capacity = float(free) + float(used)
        ratio_used = used / capacity

        data['QoS_support'] = False
        data['reserved_percentage'] = 0

        if ratio_used > self.configuration.nfs_used_ratio or \
           ratio_used >= self.configuration.nfs_oversub_ratio:
            data['reserved_percentage'] = 100

        data['total_capacity_gb'] = float(capacity) / units.Gi
        data['free_capacity_gb'] = float(free) / units.Gi

        self._stats = data
