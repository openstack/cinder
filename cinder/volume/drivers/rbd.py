#    Copyright 2013 OpenStack Foundation
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
"""RADOS Block Device Driver"""

import binascii
import errno
import json
import math
import os
import tempfile

from castellan import key_manager
from eventlet import tpool
from os_brick.initiator import linuxrbd
from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import encodeutils
from oslo_utils import excutils
from oslo_utils import fileutils
from oslo_utils import units
try:
    import rados
    import rbd
except ImportError:
    rados = None
    rbd = None
import six
from six.moves import urllib

from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder import objects
from cinder.objects import fields
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)

RBD_OPTS = [
    cfg.StrOpt('rbd_cluster_name',
               default='ceph',
               help='The name of ceph cluster'),
    cfg.StrOpt('rbd_pool',
               default='rbd',
               help='The RADOS pool where rbd volumes are stored'),
    cfg.StrOpt('rbd_user',
               help='The RADOS client name for accessing rbd volumes '
                    '- only set when using cephx authentication'),
    cfg.StrOpt('rbd_ceph_conf',
               default='',  # default determined by librados
               help='Path to the ceph configuration file'),
    cfg.BoolOpt('rbd_flatten_volume_from_snapshot',
                default=False,
                help='Flatten volumes created from snapshots to remove '
                     'dependency from volume to snapshot'),
    cfg.StrOpt('rbd_secret_uuid',
               help='The libvirt uuid of the secret for the rbd_user '
                    'volumes'),
    cfg.IntOpt('rbd_max_clone_depth',
               default=5,
               help='Maximum number of nested volume clones that are '
                    'taken before a flatten occurs. Set to 0 to disable '
                    'cloning. Note: lowering this value will not affect '
                    'existing volumes whose clone depth exceeds the new '
                    'value.'),
    cfg.IntOpt('rbd_store_chunk_size', default=4,
               help='Volumes will be chunked into objects of this size '
                    '(in megabytes).'),
    cfg.IntOpt('rados_connect_timeout', default=-1,
               help='Timeout value (in seconds) used when connecting to '
                    'ceph cluster. If value < 0, no timeout is set and '
                    'default librados value is used.'),
    cfg.IntOpt('rados_connection_retries', default=3,
               help='Number of retries if connection to ceph cluster '
                    'failed.'),
    cfg.IntOpt('rados_connection_interval', default=5,
               help='Interval value (in seconds) between connection '
                    'retries to ceph cluster.'),
    cfg.IntOpt('replication_connect_timeout', default=5,
               help='Timeout value (in seconds) used when connecting to '
                    'ceph cluster to do a demotion/promotion of volumes. '
                    'If value < 0, no timeout is set and default librados '
                    'value is used.'),
    cfg.BoolOpt('report_dynamic_total_capacity', default=True,
                help='Set to True for driver to report total capacity as a '
                     'dynamic value (used + current free) and to False to '
                     'report a static value (quota max bytes if defined and '
                     'global size of cluster if not).'),
    cfg.BoolOpt('rbd_exclusive_cinder_pool', default=True,
                help="Set to False if the pool is shared with other usages. "
                     "On exclusive use driver won't query images' provisioned "
                     "size as they will match the value calculated by the "
                     "Cinder core code for allocated_capacity_gb. This "
                     "reduces the load on the Ceph cluster as well as on the "
                     "volume service. On non exclusive use driver will query "
                     "the Ceph cluster for per image used disk, this is an "
                     "intensive operation having an independent request for "
                     "each image."),
    cfg.BoolOpt('enable_deferred_deletion', default=False,
                help='Enable deferred deletion. Upon deletion, volumes are '
                     'tagged for deletion but will only be removed '
                     'asynchronously at a later time.'),
    cfg.IntOpt('deferred_deletion_delay', default=0,
               help='Time delay in seconds before a volume is eligible '
                    'for permanent removal after being tagged for deferred '
                    'deletion.'),
    cfg.IntOpt('deferred_deletion_purge_interval', default=60,
               help='Number of seconds between runs of the periodic task '
                    'to purge volumes tagged for deletion.'),
]

CONF = cfg.CONF
CONF.register_opts(RBD_OPTS, group=configuration.SHARED_CONF_GROUP)

EXTRA_SPECS_REPL_ENABLED = "replication_enabled"
EXTRA_SPECS_MULTIATTACH = "multiattach"


# RBD
class RBDDriverException(exception.VolumeDriverException):
    message = _("RBD Cinder driver failure: %(reason)s")


class RBDVolumeProxy(object):
    """Context manager for dealing with an existing rbd volume.

    This handles connecting to rados and opening an ioctx automatically, and
    otherwise acts like a librbd Image object.

    Also this may reuse an external connection (client and ioctx args), but
    note, that caller will be responsible for opening/closing connection.
    Also `pool`, `remote`, `timeout` args will be ignored in that case.

    The underlying librados client and ioctx can be accessed as the attributes
    'client' and 'ioctx'.
    """
    def __init__(self, driver, name, pool=None, snapshot=None,
                 read_only=False, remote=None, timeout=None,
                 client=None, ioctx=None):
        self._close_conn = not (client and ioctx)
        rados_client, rados_ioctx = driver._connect_to_rados(
            pool, remote, timeout) if self._close_conn else (client, ioctx)

        if snapshot is not None:
            snapshot = utils.convert_str(snapshot)
        try:
            self.volume = driver.rbd.Image(rados_ioctx,
                                           utils.convert_str(name),
                                           snapshot=snapshot,
                                           read_only=read_only)
            self.volume = tpool.Proxy(self.volume)
        except driver.rbd.Error:
            if self._close_conn:
                driver._disconnect_from_rados(rados_client, rados_ioctx)
            raise
        self.driver = driver
        self.client = rados_client
        self.ioctx = rados_ioctx

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        try:
            self.volume.close()
        finally:
            if self._close_conn:
                self.driver._disconnect_from_rados(self.client, self.ioctx)

    def __getattr__(self, attrib):
        return getattr(self.volume, attrib)


class RADOSClient(object):
    """Context manager to simplify error handling for connecting to ceph."""
    def __init__(self, driver, pool=None):
        self.driver = driver
        self.cluster, self.ioctx = driver._connect_to_rados(pool)

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        self.driver._disconnect_from_rados(self.cluster, self.ioctx)

    @property
    def features(self):
        features = self.cluster.conf_get('rbd_default_features')
        if ((features is None) or (int(features) == 0)):
            features = self.driver.RBD_FEATURE_LAYERING
        return int(features)


@interface.volumedriver
class RBDDriver(driver.CloneableImageVD, driver.MigrateVD,
                driver.ManageableVD, driver.ManageableSnapshotsVD,
                driver.BaseVD):
    """Implements RADOS block device (RBD) volume commands."""

    VERSION = '1.2.0'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Cinder_Jenkins"

    SUPPORTS_ACTIVE_ACTIVE = True

    SYSCONFDIR = '/etc/ceph/'

    RBD_FEATURE_LAYERING = 1
    RBD_FEATURE_EXCLUSIVE_LOCK = 4
    RBD_FEATURE_OBJECT_MAP = 8
    RBD_FEATURE_FAST_DIFF = 16
    RBD_FEATURE_JOURNALING = 64
    STORAGE_PROTOCOL = 'ceph'

    def __init__(self, active_backend_id=None, *args, **kwargs):
        super(RBDDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(RBD_OPTS)
        self._stats = {}
        # allow overrides for testing
        self.rados = kwargs.get('rados', rados)
        self.rbd = kwargs.get('rbd', rbd)

        # All string args used with librbd must be None or utf-8 otherwise
        # librbd will break.
        for attr in ['rbd_cluster_name', 'rbd_user',
                     'rbd_ceph_conf', 'rbd_pool']:
            val = getattr(self.configuration, attr)
            if val is not None:
                setattr(self.configuration, attr, utils.convert_str(val))

        self._backend_name = (self.configuration.volume_backend_name or
                              self.__class__.__name__)
        self._active_backend_id = active_backend_id
        self._active_config = {}
        self._is_replication_enabled = False
        self._replication_targets = []
        self._target_names = []
        self._clone_v2_api_checked = False

        if self.rbd is not None:
            self.RBD_FEATURE_LAYERING = self.rbd.RBD_FEATURE_LAYERING
            self.RBD_FEATURE_EXCLUSIVE_LOCK = \
                self.rbd.RBD_FEATURE_EXCLUSIVE_LOCK
            self.RBD_FEATURE_OBJECT_MAP = self.rbd.RBD_FEATURE_OBJECT_MAP
            self.RBD_FEATURE_FAST_DIFF = self.rbd.RBD_FEATURE_FAST_DIFF
            self.RBD_FEATURE_JOURNALING = self.rbd.RBD_FEATURE_JOURNALING

        self.MULTIATTACH_EXCLUSIONS = (
            self.RBD_FEATURE_JOURNALING |
            self.RBD_FEATURE_FAST_DIFF |
            self.RBD_FEATURE_OBJECT_MAP |
            self.RBD_FEATURE_EXCLUSIVE_LOCK)

        self._set_keyring_attributes()

    def _set_keyring_attributes(self):
        # The rbd_keyring_conf option is not available for OpenStack usage
        # for security reasons (OSSN-0085) and in OpenStack we use
        # rbd_secret_uuid or make sure that the keyring files are present on
        # the hosts (where os-brick will look for them).
        # For cinderlib usage this option is necessary (no security issue, as
        # in those cases the contents of the connection are not available to
        # users). By using getattr Oslo-conf won't read the option from the
        # file even if it's there (because we have removed the conf option
        # definition), but cinderlib will find it because it sets the option
        # directly as an attribute.
        self.keyring_file = getattr(self.configuration, 'rbd_keyring_conf',
                                    None)

        self.keyring_data = None
        try:
            if self.keyring_file and os.path.isfile(self.keyring_file):
                with open(self.keyring_file, 'r') as k_file:
                    self.keyring_data = k_file.read()
        except IOError:
            LOG.debug('Cannot read RBD keyring file: %s.', self.keyring_file)

    @classmethod
    def get_driver_options(cls):
        additional_opts = cls._get_oslo_driver_opts(
            'replication_device', 'reserved_percentage',
            'max_over_subscription_ratio', 'volume_dd_blocksize')
        return RBD_OPTS + additional_opts

    def _show_msg_check_clone_v2_api(self, volume_name):
        if not self._clone_v2_api_checked:
            self._clone_v2_api_checked = True
            with RBDVolumeProxy(self, volume_name) as volume:
                try:
                    if (volume.volume.op_features() &
                            self.rbd.RBD_OPERATION_FEATURE_CLONE_PARENT):
                        LOG.info('Using v2 Clone API')
                        return
                except AttributeError:
                    pass
                LOG.warning('Not using v2 clone API, please upgrade to'
                            ' mimic+ and set the OSD minimum client'
                            ' compat version to mimic for better'
                            ' performance, fewer deletion issues')

    def _get_target_config(self, target_id):
        """Get a replication target from known replication targets."""
        for target in self._replication_targets:
            if target['name'] == target_id:
                return target
        if not target_id or target_id == 'default':
            return {
                'name': self.configuration.rbd_cluster_name,
                'conf': self.configuration.rbd_ceph_conf,
                'user': self.configuration.rbd_user,
                'secret_uuid': self.configuration.rbd_secret_uuid
            }
        raise exception.InvalidReplicationTarget(
            reason=_('RBD: Unknown failover target host %s.') % target_id)

    def do_setup(self, context):
        """Performs initialization steps that could raise exceptions."""
        self._do_setup_replication()
        self._active_config = self._get_target_config(self._active_backend_id)

    def _do_setup_replication(self):
        replication_devices = self.configuration.safe_get(
            'replication_device')
        if replication_devices:
            self._parse_replication_configs(replication_devices)
            self._is_replication_enabled = True
            self._target_names.append('default')

    def _parse_replication_configs(self, replication_devices):
        for replication_device in replication_devices:
            if 'backend_id' not in replication_device:
                msg = _('Missing backend_id in replication_device '
                        'configuration.')
                raise exception.InvalidConfigurationValue(msg)

            name = replication_device['backend_id']
            conf = replication_device.get('conf',
                                          self.SYSCONFDIR + name + '.conf')
            user = replication_device.get(
                'user', self.configuration.rbd_user or 'cinder')
            secret_uuid = replication_device.get(
                'secret_uuid', self.configuration.rbd_secret_uuid)
            # Pool has to be the same in all clusters
            replication_target = {'name': name,
                                  'conf': utils.convert_str(conf),
                                  'user': utils.convert_str(user),
                                  'secret_uuid': secret_uuid}
            LOG.info('Adding replication target: %s.', name)
            self._replication_targets.append(replication_target)
            self._target_names.append(name)

    def _get_config_tuple(self, remote=None):
        if not remote:
            remote = self._active_config
        return (remote.get('name'), remote.get('conf'), remote.get('user'),
                remote.get('secret_uuid', None))

    def _trash_purge(self):
        LOG.info("Purging trash for backend '%s'", self._backend_name)
        with RADOSClient(self) as client:
            for vol in self.RBDProxy().trash_list(client.ioctx):
                try:
                    self.RBDProxy().trash_remove(client.ioctx, vol.get('id'))
                    LOG.info("Deleted %s from trash for backend '%s'",
                             vol.get('name'),
                             self._backend_name)
                except Exception as e:
                    # NOTE(arne_wiebalck): trash_remove raises EPERM in case
                    # the volume's deferral time has not expired yet, so we
                    # want to explicitly handle this "normal" situation.
                    # All other exceptions, e.g. ImageBusy, are not re-raised
                    # so that the periodic purge retries on the next iteration
                    # and leaves ERRORs in the logs in case the deletion fails
                    # repeatedly.
                    if e.errno == errno.EPERM:
                        LOG.debug("%s has not expired yet on backend '%s'",
                                  vol.get('name'),
                                  self._backend_name)
                    else:
                        LOG.exception("Error deleting %s from trash "
                                      "backend '%s'",
                                      vol.get('name'),
                                      self._backend_name)

    def _start_periodic_tasks(self):
        if self.configuration.enable_deferred_deletion:
            LOG.info("Starting periodic trash purge for backend '%s'",
                     self._backend_name)
            deferred_deletion_ptask = loopingcall.FixedIntervalLoopingCall(
                self._trash_purge)
            deferred_deletion_ptask.start(
                interval=self.configuration.deferred_deletion_purge_interval)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        if rados is None:
            msg = _('rados and rbd python libraries not found')
            raise exception.VolumeBackendAPIException(data=msg)

        for attr in ['rbd_cluster_name', 'rbd_pool']:
            val = getattr(self.configuration, attr)
            if not val:
                raise exception.InvalidConfigurationValue(option=attr,
                                                          value=val)
        # NOTE: Checking connection to ceph
        # RADOSClient __init__ method invokes _connect_to_rados
        # so no need to check for self.rados.Error here.
        with RADOSClient(self):
            pass

        # NOTE(arne_wiebalck): If deferred deletion is enabled, check if the
        # local Ceph client has support for the trash API.
        if self.configuration.enable_deferred_deletion:
            if not hasattr(self.RBDProxy(), 'trash_list'):
                msg = _("Deferred deletion is enabled, but the local Ceph "
                        "client has no support for the trash API. Support "
                        "for this feature started with v12.2.0 Luminous.")
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        # If the keyring is defined (cinderlib usage), then the contents are
        # necessary.
        if self.keyring_file and not self.keyring_data:
            msg = _('No keyring data found')
            LOG.error(msg)
            raise exception.InvalidConfigurationValue(
                option='rbd_keyring_conf', value=self.keyring_file)

        self._start_periodic_tasks()

    def RBDProxy(self):
        return tpool.Proxy(self.rbd.RBD())

    def _ceph_args(self):
        args = []

        name, conf, user, secret_uuid = self._get_config_tuple()

        if user:
            args.extend(['--id', user])
        if name:
            args.extend(['--cluster', name])
        if conf:
            args.extend(['--conf', conf])

        return args

    def _connect_to_rados(self, pool=None, remote=None, timeout=None):
        @utils.retry(exception.VolumeBackendAPIException,
                     self.configuration.rados_connection_interval,
                     self.configuration.rados_connection_retries)
        def _do_conn(pool, remote, timeout):
            name, conf, user, secret_uuid = self._get_config_tuple(remote)

            if pool is not None:
                pool = utils.convert_str(pool)
            else:
                pool = self.configuration.rbd_pool

            if timeout is None:
                timeout = self.configuration.rados_connect_timeout

            LOG.debug("connecting to %(user)s@%(name)s (conf=%(conf)s, "
                      "timeout=%(timeout)s).",
                      {'user': user, 'name': name, 'conf': conf,
                       'timeout': timeout})

            client = self.rados.Rados(rados_id=user,
                                      clustername=name,
                                      conffile=conf)

            try:
                if timeout >= 0:
                    timeout = six.text_type(timeout)
                    client.conf_set('rados_osd_op_timeout', timeout)
                    client.conf_set('rados_mon_op_timeout', timeout)
                    client.conf_set('client_mount_timeout', timeout)

                client.connect()
                ioctx = client.open_ioctx(pool)
                return client, ioctx
            except self.rados.Error:
                msg = _("Error connecting to ceph cluster.")
                LOG.exception(msg)
                client.shutdown()
                raise exception.VolumeBackendAPIException(data=msg)

        return _do_conn(pool, remote, timeout)

    def _disconnect_from_rados(self, client, ioctx):
        # closing an ioctx cannot raise an exception
        ioctx.close()
        client.shutdown()

    def _get_backup_snaps(self, rbd_image):
        """Get list of any backup snapshots that exist on this volume.

        There should only ever be one but accept all since they need to be
        deleted before the volume can be.
        """
        # NOTE(dosaboy): we do the import here otherwise we get import conflict
        # issues between the rbd driver and the ceph backup driver. These
        # issues only seem to occur when NOT using them together and are
        # triggered when the ceph backup driver imports the rbd volume driver.
        from cinder.backup.drivers import ceph
        return ceph.CephBackupDriver.get_backup_snaps(rbd_image)

    def _get_mon_addrs(self):
        args = ['ceph', 'mon', 'dump', '--format=json']
        args.extend(self._ceph_args())
        out, _ = self._execute(*args)
        lines = out.split('\n')
        if lines[0].startswith('dumped monmap epoch'):
            lines = lines[1:]
        monmap = json.loads('\n'.join(lines))
        addrs = [mon['addr'] for mon in monmap['mons']]
        hosts = []
        ports = []
        for addr in addrs:
            host_port = addr[:addr.rindex('/')]
            host, port = host_port.rsplit(':', 1)
            hosts.append(host.strip('[]'))
            ports.append(port)
        return hosts, ports

    def _get_usage_info(self):
        """Calculate provisioned volume space in GiB.

        Stats report should send provisioned size of volumes (snapshot must not
        be included) and not the physical size of those volumes.

        We must include all volumes, not only Cinder created volumes, because
        Cinder created volumes are reported by the Cinder core code as
        allocated_capacity_gb.
        """
        total_provisioned = 0
        with RADOSClient(self) as client:
            for t in self.RBDProxy().list(client.ioctx):
                try:
                    with RBDVolumeProxy(self, t, read_only=True,
                                        client=client.cluster,
                                        ioctx=client.ioctx) as v:
                        size = v.size()
                except (self.rbd.ImageNotFound, self.rbd.OSError):
                    LOG.debug("Image %s is not found.", t)
                else:
                    total_provisioned += size

        total_provisioned = math.ceil(float(total_provisioned) / units.Gi)
        return total_provisioned

    def _get_pool_stats(self):
        """Gets pool free and total capacity in GiB.

        Calculate free and total capacity of the pool based on the pool's
        defined quota and pools stats.

        Returns a tuple with (free, total) where they are either unknown or a
        real number with a 2 digit precision.
        """
        pool_name = self.configuration.rbd_pool

        with RADOSClient(self) as client:
            ret, df_outbuf, __ = client.cluster.mon_command(
                '{"prefix":"df", "format":"json"}', b'')
            if ret:
                LOG.warning('Unable to get rados pool stats.')
                return 'unknown', 'unknown'

            ret, quota_outbuf, __ = client.cluster.mon_command(
                '{"prefix":"osd pool get-quota", "pool": "%s",'
                ' "format":"json"}' % pool_name, b'')
            if ret:
                LOG.warning('Unable to get rados pool quotas.')
                return 'unknown', 'unknown'

        df_outbuf = encodeutils.safe_decode(df_outbuf)
        df_data = json.loads(df_outbuf)
        pool_stats = [pool for pool in df_data['pools']
                      if pool['name'] == pool_name][0]['stats']

        quota_outbuf = encodeutils.safe_decode(quota_outbuf)
        bytes_quota = json.loads(quota_outbuf)['quota_max_bytes']
        # With quota the total is the quota limit and free is quota - used
        if bytes_quota:
            total_capacity = bytes_quota
            free_capacity = max(min(total_capacity - pool_stats['bytes_used'],
                                    pool_stats['max_avail']),
                                0)
        # Without quota free is pools max available and total is global size
        else:
            total_capacity = df_data['stats']['total_bytes']
            free_capacity = pool_stats['max_avail']

        # If we want dynamic total capacity (default behavior)
        if self.configuration.safe_get('report_dynamic_total_capacity'):
            total_capacity = free_capacity + pool_stats['bytes_used']

        free_capacity = round((float(free_capacity) / units.Gi), 2)
        total_capacity = round((float(total_capacity) / units.Gi), 2)

        return free_capacity, total_capacity

    def _update_volume_stats(self):
        location_info = '%s:%s:%s:%s:%s' % (
            self.configuration.rbd_cluster_name,
            self.configuration.rbd_ceph_conf,
            self._get_fsid(),
            self.configuration.rbd_user,
            self.configuration.rbd_pool)

        stats = {
            'vendor_name': 'Open Source',
            'driver_version': self.VERSION,
            'storage_protocol': self.STORAGE_PROTOCOL,
            'total_capacity_gb': 'unknown',
            'free_capacity_gb': 'unknown',
            'reserved_percentage': (
                self.configuration.safe_get('reserved_percentage')),
            'multiattach': True,
            'thin_provisioning_support': True,
            'max_over_subscription_ratio': (
                self.configuration.safe_get('max_over_subscription_ratio')),
            'location_info': location_info,
            'backend_state': 'down'
        }

        backend_name = self.configuration.safe_get('volume_backend_name')
        stats['volume_backend_name'] = backend_name or 'RBD'

        stats['replication_enabled'] = self._is_replication_enabled
        if self._is_replication_enabled:
            stats['replication_targets'] = self._target_names

        try:
            free_capacity, total_capacity = self._get_pool_stats()
            stats['free_capacity_gb'] = free_capacity
            stats['total_capacity_gb'] = total_capacity

            # For exclusive pools let scheduler set provisioned_capacity_gb to
            # allocated_capacity_gb, and for non exclusive query the value.
            if not self.configuration.safe_get('rbd_exclusive_cinder_pool'):
                total_gbi = self._get_usage_info()
                stats['provisioned_capacity_gb'] = total_gbi

            stats['backend_state'] = 'up'
        except self.rados.Error:
            # just log and return unknown capacities and let scheduler set
            # provisioned_capacity_gb = allocated_capacity_gb
            LOG.exception('error refreshing volume stats')
        self._stats = stats

    def _get_clone_depth(self, client, volume_name, depth=0):
        """Returns the number of ancestral clones of the given volume."""
        parent_volume = self.rbd.Image(client.ioctx, volume_name)
        try:
            _pool, parent, _snap = self._get_clone_info(parent_volume,
                                                        volume_name)
        finally:
            parent_volume.close()

        if not parent:
            return depth

        return self._get_clone_depth(client, parent, depth + 1)

    def _extend_if_required(self, volume, src_vref):
        """Extends a volume if required

        In case src_vref size is smaller than the size if the requested
        new volume call _resize().
        """
        if volume.size != src_vref.size:
            LOG.debug("resize volume '%(dst_vol)s' from %(src_size)d to "
                      "%(dst_size)d",
                      {'dst_vol': volume.name, 'src_size': src_vref.size,
                       'dst_size': volume.size})
            self._resize(volume)

    def create_cloned_volume(self, volume, src_vref):
        """Create a cloned volume from another volume.

        Since we are cloning from a volume and not a snapshot, we must first
        create a snapshot of the source volume.

        The user has the option to limit how long a volume's clone chain can be
        by setting rbd_max_clone_depth. If a clone is made of another clone
        and that clone has rbd_max_clone_depth clones behind it, the dest
        volume will be flattened.
        """
        src_name = utils.convert_str(src_vref.name)
        dest_name = utils.convert_str(volume.name)
        clone_snap = "%s.clone_snap" % dest_name

        # Do full copy if requested
        if self.configuration.rbd_max_clone_depth <= 0:
            with RBDVolumeProxy(self, src_name, read_only=True) as vol:
                vol.copy(vol.ioctx, dest_name)
                self._extend_if_required(volume, src_vref)
            return

        # Otherwise do COW clone.
        with RADOSClient(self) as client:
            src_volume = self.rbd.Image(client.ioctx, src_name)
            LOG.debug("creating snapshot='%s'", clone_snap)
            try:
                # Create new snapshot of source volume
                src_volume.create_snap(clone_snap)
                src_volume.protect_snap(clone_snap)
                # Now clone source volume snapshot
                LOG.debug("cloning '%(src_vol)s@%(src_snap)s' to "
                          "'%(dest)s'",
                          {'src_vol': src_name, 'src_snap': clone_snap,
                           'dest': dest_name})
                self.RBDProxy().clone(client.ioctx, src_name, clone_snap,
                                      client.ioctx, dest_name,
                                      features=client.features)
            except Exception as e:
                src_volume.unprotect_snap(clone_snap)
                src_volume.remove_snap(clone_snap)
                src_volume.close()
                msg = (_("Failed to clone '%(src_vol)s@%(src_snap)s' to "
                         "'%(dest)s', error: %(error)s") %
                       {'src_vol': src_name,
                        'src_snap': clone_snap,
                        'dest': dest_name,
                        'error': e})
                LOG.exception(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            depth = self._get_clone_depth(client, src_name)
            # If dest volume is a clone and rbd_max_clone_depth reached,
            # flatten the dest after cloning. Zero rbd_max_clone_depth means
            # volumes are always flattened.
            if depth >= self.configuration.rbd_max_clone_depth:
                LOG.info("maximum clone depth (%d) has been reached - "
                         "flattening dest volume",
                         self.configuration.rbd_max_clone_depth)

                # Flatten destination volume
                try:
                    with RBDVolumeProxy(self, dest_name, client=client,
                                        ioctx=client.ioctx) as dest_volume:
                        LOG.debug("flattening dest volume %s", dest_name)
                        dest_volume.flatten()
                except Exception as e:
                    msg = (_("Failed to flatten volume %(volume)s with "
                             "error: %(error)s.") %
                           {'volume': dest_name,
                            'error': e})
                    LOG.exception(msg)
                    src_volume.close()
                    raise exception.VolumeBackendAPIException(data=msg)

                try:
                    # remove temporary snap
                    LOG.debug("remove temporary snap %s", clone_snap)
                    src_volume.unprotect_snap(clone_snap)
                    src_volume.remove_snap(clone_snap)
                except Exception as e:
                    msg = (_("Failed to remove temporary snap "
                             "%(snap_name)s, error: %(error)s") %
                           {'snap_name': clone_snap,
                            'error': e})
                    LOG.exception(msg)
                    src_volume.close()
                    raise exception.VolumeBackendAPIException(data=msg)

            try:
                volume_update = self._setup_volume(volume)
            except Exception:
                self.RBDProxy().remove(client.ioctx, dest_name)
                src_volume.unprotect_snap(clone_snap)
                src_volume.remove_snap(clone_snap)
                err_msg = (_('Failed to enable image replication'))
                raise exception.ReplicationError(reason=err_msg,
                                                 volume_id=volume.id)
            finally:
                src_volume.close()

            self._extend_if_required(volume, src_vref)

        LOG.debug("clone created successfully")
        return volume_update

    def _enable_replication(self, volume):
        """Enable replication for a volume.

        Returns required volume update.
        """
        vol_name = utils.convert_str(volume.name)
        with RBDVolumeProxy(self, vol_name) as image:
            had_exclusive_lock = (image.features() &
                                  self.RBD_FEATURE_EXCLUSIVE_LOCK)
            had_journaling = image.features() & self.RBD_FEATURE_JOURNALING
            if not had_exclusive_lock:
                image.update_features(self.RBD_FEATURE_EXCLUSIVE_LOCK,
                                      True)
            if not had_journaling:
                image.update_features(self.RBD_FEATURE_JOURNALING, True)
            image.mirror_image_enable()

        driver_data = self._dumps({
            'had_journaling': bool(had_journaling),
            'had_exclusive_lock': bool(had_exclusive_lock)
        })
        return {'replication_status': fields.ReplicationStatus.ENABLED,
                'replication_driver_data': driver_data}

    def _enable_multiattach(self, volume):
        vol_name = utils.convert_str(volume.name)
        with RBDVolumeProxy(self, vol_name) as image:
            image_features = image.features()
            change_features = self.MULTIATTACH_EXCLUSIONS & image_features
            image.update_features(change_features, False)

        return {'provider_location':
                self._dumps({'saved_features': image_features})}

    def _disable_multiattach(self, volume):
        vol_name = utils.convert_str(volume.name)
        with RBDVolumeProxy(self, vol_name) as image:
            try:
                provider_location = json.loads(volume.provider_location)
                image_features = provider_location['saved_features']
                change_features = self.MULTIATTACH_EXCLUSIONS & image_features
                image.update_features(change_features, True)
            except IndexError:
                msg = "Could not find saved image features."
                raise RBDDriverException(reason=msg)
            except self.rbd.InvalidArgument:
                msg = "Failed to restore image features."
                raise RBDDriverException(reason=msg)

        return {'provider_location': None}

    def _is_replicated_type(self, volume_type):
        try:
            extra_specs = volume_type.extra_specs
            LOG.debug('extra_specs: %s', extra_specs)
            return extra_specs.get(EXTRA_SPECS_REPL_ENABLED) == "<is> True"
        except Exception:
            LOG.debug('Unable to retrieve extra specs info')
            return False

    def _is_multiattach_type(self, volume_type):
        try:
            extra_specs = volume_type.extra_specs
            LOG.debug('extra_specs: %s', extra_specs)
            return extra_specs.get(EXTRA_SPECS_MULTIATTACH) == "<is> True"
        except Exception:
            LOG.debug('Unable to retrieve extra specs info')
            return False

    def _setup_volume(self, volume, volume_type=None):

        if volume_type:
            had_replication = self._is_replicated_type(volume.volume_type)
            had_multiattach = self._is_multiattach_type(volume.volume_type)
        else:
            had_replication = False
            had_multiattach = False
            volume_type = volume.volume_type

        want_replication = self._is_replicated_type(volume_type)
        want_multiattach = self._is_multiattach_type(volume_type)

        if want_replication and want_multiattach:
            msg = _('Replication and Multiattach are mutually exclusive.')
            raise RBDDriverException(reason=msg)

        volume_update = dict()

        if want_replication:
            if had_multiattach:
                volume_update.update(self._disable_multiattach(volume))
            if not had_replication:
                try:
                    volume_update.update(self._enable_replication(volume))
                except Exception:
                    err_msg = (_('Failed to enable image replication'))
                    raise exception.ReplicationError(reason=err_msg,
                                                     volume_id=volume.id)
        elif had_replication:
            try:
                volume_update.update(self._disable_replication(volume))
            except Exception:
                err_msg = (_('Failed to disable image replication'))
                raise exception.ReplicationError(reason=err_msg,
                                                 volume_id=volume.id)
        elif self._is_replication_enabled:
            volume_update.update({'replication_status':
                                  fields.ReplicationStatus.DISABLED})

        if want_multiattach:
            volume_update.update(self._enable_multiattach(volume))
        elif had_multiattach:
            volume_update.update(self._disable_multiattach(volume))

        return volume_update

    def _create_encrypted_volume(self, volume, context):
        """Create an encrypted volume.

        This works by creating an encrypted image locally,
        and then uploading it to the volume.
        """
        encryption = volume_utils.check_encryption_provider(volume, context)

        # Fetch the key associated with the volume and decode the passphrase
        keymgr = key_manager.API(CONF)
        key = keymgr.get(context, encryption['encryption_key_id'])
        passphrase = binascii.hexlify(key.get_encoded()).decode('utf-8')

        # create a file
        tmp_dir = volume_utils.image_conversion_dir()

        with tempfile.NamedTemporaryFile(dir=tmp_dir) as tmp_image:
            with tempfile.NamedTemporaryFile(dir=tmp_dir) as tmp_key:
                with open(tmp_key.name, 'w') as f:
                    f.write(passphrase)

                cipher_spec = image_utils.decode_cipher(encryption['cipher'],
                                                        encryption['key_size'])

                create_cmd = (
                    'qemu-img', 'create', '-f', 'luks',
                    '-o', 'cipher-alg=%(cipher_alg)s,'
                    'cipher-mode=%(cipher_mode)s,'
                    'ivgen-alg=%(ivgen_alg)s' % cipher_spec,
                    '--object', 'secret,id=luks_sec,'
                    'format=raw,file=%(passfile)s' % {'passfile':
                                                      tmp_key.name},
                    '-o', 'key-secret=luks_sec',
                    tmp_image.name,
                    '%sM' % (volume.size * 1024))
                self._execute(*create_cmd)

            # Copy image into RBD
            chunk_size = self.configuration.rbd_store_chunk_size * units.Mi
            order = int(math.log(chunk_size, 2))

            cmd = ['rbd', 'import',
                   '--pool', self.configuration.rbd_pool,
                   '--order', order,
                   tmp_image.name, volume.name]
            cmd.extend(self._ceph_args())
            self._execute(*cmd)

    def create_volume(self, volume):
        """Creates a logical volume."""

        if volume.encryption_key_id:
            return self._create_encrypted_volume(volume, volume.obj_context)

        size = int(volume.size) * units.Gi

        LOG.debug("creating volume '%s'", volume.name)

        chunk_size = self.configuration.rbd_store_chunk_size * units.Mi
        order = int(math.log(chunk_size, 2))
        vol_name = utils.convert_str(volume.name)

        with RADOSClient(self) as client:
            self.RBDProxy().create(client.ioctx,
                                   vol_name,
                                   size,
                                   order,
                                   old_format=False,
                                   features=client.features)

        try:
            volume_update = self._setup_volume(volume)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Error creating rbd image %(vol)s.',
                          {'vol': vol_name})
                self.RBDProxy().remove(client.ioctx, vol_name)

        return volume_update

    def _flatten(self, pool, volume_name):
        LOG.debug('flattening %(pool)s/%(img)s',
                  dict(pool=pool, img=volume_name))
        with RBDVolumeProxy(self, volume_name, pool) as vol:
            vol.flatten()

    def _get_stripe_unit(self, ioctx, volume_name):
        """Return the correct stripe unit for a cloned volume.

        A cloned volume must be created with a stripe unit at least as large
        as the source volume.  We compute the desired stripe width from
        rbd_store_chunk_size and compare that to the incoming source volume's
        stripe width, selecting the larger to avoid error.
        """
        default_stripe_unit = \
            self.configuration.rbd_store_chunk_size * units.Mi

        image = self.rbd.Image(ioctx, volume_name)
        try:
            image_stripe_unit = image.stripe_unit()
        finally:
            image.close()

        return max(image_stripe_unit, default_stripe_unit)

    def _clone(self, volume, src_pool, src_image, src_snap):
        LOG.debug('cloning %(pool)s/%(img)s@%(snap)s to %(dst)s',
                  dict(pool=src_pool, img=src_image, snap=src_snap,
                       dst=volume.name))

        vol_name = utils.convert_str(volume.name)

        with RADOSClient(self, src_pool) as src_client:
            stripe_unit = self._get_stripe_unit(src_client.ioctx, src_image)
            order = int(math.log(stripe_unit, 2))
            with RADOSClient(self) as dest_client:
                self.RBDProxy().clone(src_client.ioctx,
                                      utils.convert_str(src_image),
                                      utils.convert_str(src_snap),
                                      dest_client.ioctx,
                                      vol_name,
                                      features=src_client.features,
                                      order=order)
            try:
                volume_update = self._setup_volume(volume)
            except Exception:
                self.RBDProxy().remove(dest_client.ioctx, vol_name)
                err_msg = (_('Failed to enable image replication'))
                raise exception.ReplicationError(reason=err_msg,
                                                 volume_id=volume.id)
            return volume_update or {}

    def _resize(self, volume, **kwargs):
        size = kwargs.get('size', None)
        if not size:
            size = int(volume.size) * units.Gi

        with RBDVolumeProxy(self, volume.name) as vol:
            vol.resize(size)

    def _calculate_new_size(self, size_diff, volume_name):
        with RBDVolumeProxy(self, volume_name) as vol:
            current_size_bytes = vol.volume.size()
        size_diff_bytes = size_diff * units.Gi
        new_size_bytes = current_size_bytes + size_diff_bytes
        return new_size_bytes

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        volume_update = self._clone(volume, self.configuration.rbd_pool,
                                    snapshot.volume_name, snapshot.name)
        if self.configuration.rbd_flatten_volume_from_snapshot:
            self._flatten(self.configuration.rbd_pool, volume.name)

        snap_vol_size = snapshot.volume_size
        # In case the destination size is bigger than the snapshot size
        # we should resize. In particular when the destination volume
        # is encrypted we should consider the encryption header size.
        # Because of this, we need to calculate the difference size to
        # provide the size that the user is expecting.
        # Otherwise if the destination volume size is equal to the
        # source volume size we don't perform a resize.
        if volume.size > snap_vol_size:
            new_size = None
            # In case the volume is encrypted we need to consider the
            # size of the encryption header when resizing the volume
            if volume.encryption_key_id:
                size_diff = volume.size - snap_vol_size
                new_size = self._calculate_new_size(size_diff, volume.name)
            self._resize(volume, size=new_size)

        self._show_msg_check_clone_v2_api(snapshot.volume_name)
        return volume_update

    def _delete_backup_snaps(self, rbd_image):
        backup_snaps = self._get_backup_snaps(rbd_image)
        if backup_snaps:
            for snap in backup_snaps:
                rbd_image.remove_snap(snap['name'])
        else:
            LOG.debug("volume has no backup snaps")

    def _get_clone_info(self, volume, volume_name, snap=None):
        """If volume is a clone, return its parent info.

        Returns a tuple of (pool, parent, snap). A snapshot may optionally be
        provided for the case where a cloned volume has been flattened but it's
        snapshot still depends on the parent.
        """
        try:
            if snap:
                volume.set_snap(snap)
            pool, parent, parent_snap = tuple(volume.parent_info())
            if snap:
                volume.set_snap(None)
            # Strip the tag off the end of the volume name since it will not be
            # in the snap name.
            if volume_name.endswith('.deleted'):
                volume_name = volume_name[:-len('.deleted')]
            # Now check the snap name matches.
            if parent_snap == "%s.clone_snap" % volume_name:
                return pool, parent, parent_snap
        except self.rbd.ImageNotFound:
            LOG.debug("Volume %s is not a clone.", volume_name)
            volume.set_snap(None)

        return (None, None, None)

    def _get_children_info(self, volume, snap):
        """List children for the given snapshot of a volume(image).

        Returns a list of (pool, image).
        """

        children_list = []

        if snap:
            volume.set_snap(snap)
            children_list = volume.list_children()
            volume.set_snap(None)

        return children_list

    def _delete_clone_parent_refs(self, client, parent_name, parent_snap):
        """Walk back up the clone chain and delete references.

        Deletes references i.e. deleted parent volumes and snapshots.
        """
        parent_rbd = self.rbd.Image(client.ioctx, parent_name)
        parent_has_snaps = False
        try:
            # Check for grandparent
            _pool, g_parent, g_parent_snap = self._get_clone_info(parent_rbd,
                                                                  parent_name,
                                                                  parent_snap)

            LOG.debug("deleting parent snapshot %s", parent_snap)
            parent_rbd.unprotect_snap(parent_snap)
            parent_rbd.remove_snap(parent_snap)

            parent_has_snaps = bool(list(parent_rbd.list_snaps()))
        finally:
            parent_rbd.close()

        # If parent has been deleted in Cinder, delete the silent reference and
        # keep walking up the chain if it is itself a clone.
        if (not parent_has_snaps) and parent_name.endswith('.deleted'):
            LOG.debug("deleting parent %s", parent_name)
            if self.configuration.enable_deferred_deletion:
                LOG.debug("moving volume %s to trash", parent_name)
                delay = self.configuration.deferred_deletion_delay
                self.RBDProxy().trash_move(client.ioctx,
                                           parent_name,
                                           delay)
            else:
                self.RBDProxy().remove(client.ioctx, parent_name)

            # Now move up to grandparent if there is one
            if g_parent:
                self._delete_clone_parent_refs(client, g_parent, g_parent_snap)

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        # NOTE(dosaboy): this was broken by commit cbe1d5f. Ensure names are
        #                utf-8 otherwise librbd will barf.
        volume_name = utils.convert_str(volume.name)
        with RADOSClient(self) as client:
            try:
                rbd_image = self.rbd.Image(client.ioctx, volume_name)
            except self.rbd.ImageNotFound:
                LOG.info("volume %s no longer exists in backend",
                         volume_name)
                return

            clone_snap = None
            parent = None

            # Ensure any backup snapshots are deleted
            self._delete_backup_snaps(rbd_image)

            # If the volume has non-clone snapshots this delete is expected to
            # raise VolumeIsBusy so do so straight away.
            try:
                snaps = rbd_image.list_snaps()
                for snap in snaps:
                    if snap['name'].endswith('.clone_snap'):
                        LOG.debug("volume has clone snapshot(s)")
                        # We grab one of these and use it when fetching parent
                        # info in case the volume has been flattened.
                        clone_snap = snap['name']
                        break

                # Determine if this volume is itself a clone
                _pool, parent, parent_snap = self._get_clone_info(rbd_image,
                                                                  volume_name,
                                                                  clone_snap)
            finally:
                rbd_image.close()

            @utils.retry(self.rbd.ImageBusy,
                         self.configuration.rados_connection_interval,
                         self.configuration.rados_connection_retries)
            def _try_remove_volume(client, volume_name):
                if self.configuration.enable_deferred_deletion:
                    delay = self.configuration.deferred_deletion_delay
                else:
                    try:
                        self.RBDProxy().remove(client.ioctx, volume_name)
                        return
                    except (self.rbd.ImageHasSnapshots, self.rbd.ImageBusy):
                        delay = 0
                LOG.debug("moving volume %s to trash", volume_name)
                # When using the RBD v2 clone api, deleting a volume
                # that has a snapshot in the trash space raises a
                # busy exception.
                # In order to solve this, call the trash operation
                # which should succeed when the volume has
                # dependencies.
                self.RBDProxy().trash_move(client.ioctx,
                                           volume_name,
                                           delay)

            if clone_snap is None:
                LOG.debug("deleting rbd volume %s", volume_name)
                try:
                    _try_remove_volume(client, volume_name)
                except self.rbd.ImageBusy:
                    msg = (_("ImageBusy error raised while deleting rbd "
                             "volume. This may have been caused by a "
                             "connection from a client that has crashed and, "
                             "if so, may be resolved by retrying the delete "
                             "after 30 seconds has elapsed."))
                    LOG.warning(msg)
                    # Now raise this so that the volume stays available and the
                    # deletion can be retried.
                    raise exception.VolumeIsBusy(msg, volume_name=volume_name)
                except self.rbd.ImageNotFound:
                    LOG.info("RBD volume %s not found, allowing delete "
                             "operation to proceed.", volume_name)
                    return

                # If it is a clone, walk back up the parent chain deleting
                # references.
                if parent:
                    LOG.debug("volume is a clone so cleaning references")
                    self._delete_clone_parent_refs(client, parent, parent_snap)
            else:
                # If the volume has copy-on-write clones we will not be able to
                # delete it. Instead we will keep it as a silent volume which
                # will be deleted when it's snapshot and clones are deleted.
                new_name = "%s.deleted" % (volume_name)
                self.RBDProxy().rename(client.ioctx, volume_name, new_name)

    def create_snapshot(self, snapshot):
        """Creates an rbd snapshot."""
        with RBDVolumeProxy(self, snapshot.volume_name) as volume:
            snap = utils.convert_str(snapshot.name)
            volume.create_snap(snap)
            volume.protect_snap(snap)

    def delete_snapshot(self, snapshot):
        """Deletes an rbd snapshot."""
        # NOTE(dosaboy): this was broken by commit cbe1d5f. Ensure names are
        #                utf-8 otherwise librbd will barf.
        volume_name = utils.convert_str(snapshot.volume_name)
        snap_name = utils.convert_str(snapshot.name)

        with RBDVolumeProxy(self, volume_name) as volume:
            try:
                volume.unprotect_snap(snap_name)
            except self.rbd.InvalidArgument:
                LOG.info(
                    "InvalidArgument: Unable to unprotect snapshot %s.",
                    snap_name)
            except self.rbd.ImageNotFound:
                LOG.info(
                    "ImageNotFound: Unable to unprotect snapshot %s.",
                    snap_name)
            except self.rbd.ImageBusy:
                children_list = self._get_children_info(volume, snap_name)

                if children_list:
                    for (pool, image) in children_list:
                        LOG.info('Image %(pool)s/%(image)s is dependent '
                                 'on the snapshot %(snap)s.',
                                 {'pool': pool,
                                  'image': image,
                                  'snap': snap_name})

                raise exception.SnapshotIsBusy(snapshot_name=snap_name)
            try:
                volume.remove_snap(snap_name)
            except self.rbd.ImageNotFound:
                LOG.info("Snapshot %s does not exist in backend.",
                         snap_name)

    def snapshot_revert_use_temp_snapshot(self):
        """Disable the use of a temporary snapshot on revert."""
        return False

    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert a volume to a given snapshot."""
        # NOTE(rosmaita): The Ceph documentation notes that this operation is
        # inefficient on the backend for large volumes, and that the preferred
        # method of returning to a pre-existing state in Ceph is to clone from
        # a snapshot.
        # So why don't we do something like that here?
        # (a) an end user can do the more efficient operation on their own if
        #     they value speed over the convenience of reverting their existing
        #     volume
        # (b) revert-to-snapshot is properly a backend operation, and should
        #     be handled by the backend -- trying to "fake it" in this driver
        #     is both dishonest and likely to cause subtle bugs
        # (c) the Ceph project undergoes continual improvement.  It may be
        #     the case that there are things an operator can do on the Ceph
        #     side (for example, use BlueStore for the Ceph backend storage)
        #     to improve the efficiency of this operation.
        # Thus, a motivated operator reading this is encouraged to consult
        # the Ceph documentation.
        with RBDVolumeProxy(self, volume.name) as image:
            image.rollback_to_snap(snapshot.name)

    def _disable_replication(self, volume):
        """Disable replication on the given volume."""
        vol_name = utils.convert_str(volume.name)
        with RBDVolumeProxy(self, vol_name) as image:
            image.mirror_image_disable(False)
            driver_data = json.loads(volume.replication_driver_data)
            # If 'journaling' and/or 'exclusive-lock' have
            # been enabled in '_enable_replication',
            # they will be disabled here. If not, it will keep
            # what it was before.
            if not driver_data['had_journaling']:
                image.update_features(self.RBD_FEATURE_JOURNALING, False)
            if not driver_data['had_exclusive_lock']:
                image.update_features(self.RBD_FEATURE_EXCLUSIVE_LOCK, False)
        return {'replication_status': fields.ReplicationStatus.DISABLED,
                'replication_driver_data': None}

    def retype(self, context, volume, new_type, diff, host):
        """Retype from one volume type to another on the same backend."""
        return True, self._setup_volume(volume, new_type)

    def _dumps(self, obj):
        return json.dumps(obj, separators=(',', ':'), sort_keys=True)

    def _exec_on_volume(self, volume_name, remote, operation, *args, **kwargs):
        @utils.retry(rbd.ImageBusy,
                     self.configuration.rados_connection_interval,
                     self.configuration.rados_connection_retries)
        def _do_exec():
            timeout = self.configuration.replication_connect_timeout
            with RBDVolumeProxy(self, volume_name, self.configuration.rbd_pool,
                                remote=remote, timeout=timeout) as rbd_image:
                return getattr(rbd_image, operation)(*args, **kwargs)
        return _do_exec()

    def _failover_volume(self, volume, remote, is_demoted, replication_status):
        """Process failover for a volume.

        There are 2 different cases that will return different update values
        for the volume:

        - Volume has replication enabled and failover succeeded: Set
          replication status to failed-over.
        - Volume has replication enabled and failover fails: Set status to
          error, replication status to failover-error, and store previous
          status in previous_status field.
        """
        # Failover is allowed when volume has it enabled or it has already
        # failed over, because we may want to do a second failover.
        vol_name = utils.convert_str(volume.name)
        try:
            self._exec_on_volume(vol_name, remote,
                                 'mirror_image_promote', not is_demoted)

            return {'volume_id': volume.id,
                    'updates': {'replication_status': replication_status}}
        except Exception as e:
            replication_status = fields.ReplicationStatus.FAILOVER_ERROR
            LOG.error('Failed to failover volume %(volume)s with '
                      'error: %(error)s.',
                      {'volume': volume.name, 'error': e})

        # Failover failed
        error_result = {
            'volume_id': volume.id,
            'updates': {
                'status': 'error',
                'previous_status': volume.status,
                'replication_status': replication_status
            }
        }

        return error_result

    def _demote_volumes(self, volumes, until_failure=True):
        """Try to demote volumes on the current primary cluster."""
        result = []
        try_demoting = True
        for volume in volumes:
            demoted = False
            if try_demoting:
                vol_name = utils.convert_str(volume.name)
                try:
                    self._exec_on_volume(vol_name, self._active_config,
                                         'mirror_image_demote')
                    demoted = True
                except Exception as e:
                    LOG.debug('Failed to demote %(volume)s with error: '
                              '%(error)s.',
                              {'volume': volume.name, 'error': e})
                    try_demoting = not until_failure
            result.append(demoted)
        return result

    def _get_failover_target_config(self, secondary_id=None):
        if not secondary_id:
            # In auto mode exclude failback and active
            candidates = set(self._target_names).difference(
                ('default', self._active_backend_id))
            if not candidates:
                raise exception.InvalidReplicationTarget(
                    reason=_('RBD: No available failover target host.'))
            secondary_id = candidates.pop()
        return secondary_id, self._get_target_config(secondary_id)

    def failover(self, context, volumes, secondary_id=None, groups=None):
        """Failover replicated volumes."""
        LOG.info('RBD driver failover started.')
        if not self._is_replication_enabled:
            raise exception.UnableToFailOver(
                reason=_('RBD: Replication is not enabled.'))

        if secondary_id == 'default':
            replication_status = fields.ReplicationStatus.ENABLED
        else:
            replication_status = fields.ReplicationStatus.FAILED_OVER

        secondary_id, remote = self._get_failover_target_config(secondary_id)

        # Try to demote the volumes first
        demotion_results = self._demote_volumes(volumes)

        # Do the failover taking into consideration if they have been demoted
        updates = [self._failover_volume(volume, remote, is_demoted,
                                         replication_status)
                   for volume, is_demoted in zip(volumes, demotion_results)]

        LOG.info('RBD driver failover completed.')
        return secondary_id, updates, []

    def failover_completed(self, context, secondary_id=None):
        """Failover to replication target."""
        LOG.info('RBD driver failover completion started.')
        secondary_id, remote = self._get_failover_target_config(secondary_id)

        self._active_backend_id = secondary_id
        self._active_config = remote
        LOG.info('RBD driver failover completion completed.')

    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        """Failover to replication target.

        This function combines calls to failover() and failover_completed() to
        perform failover when Active/Active is not enabled.
        """
        active_backend_id, volume_update_list, group_update_list = (
            self.failover(context, volumes, secondary_id, groups))
        self.failover_completed(context, secondary_id)
        return active_backend_id, volume_update_list, group_update_list

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        pass

    def create_export(self, context, volume, connector):
        """Exports the volume."""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass

    def initialize_connection(self, volume, connector):
        hosts, ports = self._get_mon_addrs()
        name, conf, user, secret_uuid = self._get_config_tuple()
        data = {
            'driver_volume_type': 'rbd',
            'data': {
                'name': '%s/%s' % (self.configuration.rbd_pool,
                                   volume.name),
                'hosts': hosts,
                'ports': ports,
                'cluster_name': name,
                'auth_enabled': (user is not None),
                'auth_username': user,
                'secret_type': 'ceph',
                'secret_uuid': secret_uuid,
                'volume_id': volume.id,
                "discard": True,
            }
        }
        if self.keyring_data:
            data['data']['keyring'] = self.keyring_data
        LOG.debug('connection data: %s', data)
        return data

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def _parse_location(self, location):
        prefix = 'rbd://'
        if not location.startswith(prefix):
            reason = _('Not stored in rbd')
            raise exception.ImageUnacceptable(image_id=location, reason=reason)
        pieces = [urllib.parse.unquote(loc)
                  for loc in location[len(prefix):].split('/')]
        if any(map(lambda p: p == '', pieces)):
            reason = _('Blank components')
            raise exception.ImageUnacceptable(image_id=location, reason=reason)
        if len(pieces) != 4:
            reason = _('Not an rbd snapshot')
            raise exception.ImageUnacceptable(image_id=location, reason=reason)
        return pieces

    def _get_fsid(self):
        with RADOSClient(self) as client:
            # Librados's get_fsid is represented as binary
            # in py3 instead of str as it is in py2.
            # This causes problems with cinder rbd
            # driver as we rely on get_fsid return value
            # which should be string, not bytes.
            # Decode binary to str fixes these issues.
            # Fix with encodeutils.safe_decode CAN BE REMOVED
            # after librados's fix will be in stable for some time.
            #
            # More informations:
            # https://bugs.launchpad.net/glance-store/+bug/1816721
            # https://bugs.launchpad.net/cinder/+bug/1816468
            # https://tracker.ceph.com/issues/38381
            return encodeutils.safe_decode(client.cluster.get_fsid())

    def _is_cloneable(self, image_location, image_meta):
        try:
            fsid, pool, image, snapshot = self._parse_location(image_location)
        except exception.ImageUnacceptable as e:
            LOG.debug('not cloneable: %s.', e)
            return False

        if self._get_fsid() != fsid:
            LOG.debug('%s is in a different ceph cluster.', image_location)
            return False

        if image_meta['disk_format'] != 'raw':
            LOG.debug("rbd image clone requires image format to be "
                      "'raw' but image %(image)s is '%(format)s'",
                      {"image": image_location,
                       "format": image_meta['disk_format']})
            return False

        # check that we can read the image
        try:
            with RBDVolumeProxy(self, image,
                                pool=pool,
                                snapshot=snapshot,
                                read_only=True):
                return True
        except self.rbd.Error as e:
            LOG.debug('Unable to open image %(loc)s: %(err)s.',
                      dict(loc=image_location, err=e))
            return False

    def clone_image(self, context, volume,
                    image_location, image_meta,
                    image_service):
        if image_location:
            # Note: image_location[0] is glance image direct_url.
            # image_location[1] contains the list of all locations (including
            # direct_url) or None if show_multiple_locations is False in
            # glance configuration.
            if image_location[1]:
                url_locations = [location['url'] for
                                 location in image_location[1]]
            else:
                url_locations = [image_location[0]]

            # iterate all locations to look for a cloneable one.
            for url_location in url_locations:
                if url_location and self._is_cloneable(
                        url_location, image_meta):
                    _prefix, pool, image, snapshot = \
                        self._parse_location(url_location)
                    volume_update = self._clone(volume, pool, image, snapshot)
                    volume_update['provider_location'] = None
                    self._resize(volume)
                    return volume_update, True
        return ({}, False)

    def copy_image_to_encrypted_volume(self, context, volume, image_service,
                                       image_id):
        self._copy_image_to_volume(context, volume, image_service, image_id,
                                   encrypted=True)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        self._copy_image_to_volume(context, volume, image_service, image_id)

    def _encrypt_image(self, context, volume, tmp_dir, src_image_path):
        encryption = volume_utils.check_encryption_provider(volume, context)

        # Fetch the key associated with the volume and decode the passphrase
        keymgr = key_manager.API(CONF)
        key = keymgr.get(context, encryption['encryption_key_id'])
        passphrase = binascii.hexlify(key.get_encoded()).decode('utf-8')

        # Decode the dm-crypt style cipher spec into something qemu-img can use
        cipher_spec = image_utils.decode_cipher(encryption['cipher'],
                                                encryption['key_size'])

        tmp_dir = volume_utils.image_conversion_dir()

        with tempfile.NamedTemporaryFile(prefix='luks_',
                                         dir=tmp_dir) as pass_file:
            with open(pass_file.name, 'w') as f:
                f.write(passphrase)

            # Convert the raw image to luks
            dest_image_path = src_image_path + '.luks'
            try:
                image_utils.convert_image(src_image_path, dest_image_path,
                                          'luks', src_format='raw',
                                          cipher_spec=cipher_spec,
                                          passphrase_file=pass_file.name)

                # Replace the original image with the now encrypted image
                os.rename(dest_image_path, src_image_path)
            finally:
                fileutils.delete_if_exists(dest_image_path)

    def _copy_image_to_volume(self, context, volume, image_service, image_id,
                              encrypted=False):

        tmp_dir = volume_utils.image_conversion_dir()

        with tempfile.NamedTemporaryFile(dir=tmp_dir) as tmp:
            image_utils.fetch_to_raw(context, image_service, image_id,
                                     tmp.name,
                                     self.configuration.volume_dd_blocksize,
                                     size=volume.size)

            if encrypted:
                self._encrypt_image(context, volume, tmp_dir, tmp.name)

            @utils.retry(exception.VolumeIsBusy,
                         self.configuration.rados_connection_interval,
                         self.configuration.rados_connection_retries)
            def _delete_volume(volume):
                self.delete_volume(volume)

            _delete_volume(volume)

            chunk_size = self.configuration.rbd_store_chunk_size * units.Mi
            order = int(math.log(chunk_size, 2))
            # keep using the command line import instead of librbd since it
            # detects zeroes to preserve sparseness in the image
            args = ['rbd', 'import',
                    '--pool', self.configuration.rbd_pool,
                    '--order', order,
                    tmp.name, volume.name,
                    '--new-format']
            args.extend(self._ceph_args())
            self._try_execute(*args)
        self._resize(volume)
        # We may need to re-enable replication because we have deleted the
        # original image and created a new one using the command line import.
        try:
            self._setup_volume(volume)
        except Exception:
            err_msg = (_('Failed to enable image replication'))
            raise exception.ReplicationError(reason=err_msg,
                                             volume_id=volume.id)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        tmp_dir = volume_utils.image_conversion_dir()
        tmp_file = os.path.join(tmp_dir,
                                volume.name + '-' + image_meta['id'])
        with fileutils.remove_path_on_error(tmp_file):
            args = ['rbd', 'export',
                    '--pool', self.configuration.rbd_pool,
                    volume.name, tmp_file]
            args.extend(self._ceph_args())
            self._try_execute(*args)
            volume_utils.upload_volume(context, image_service,
                                       image_meta, tmp_file,
                                       volume)
        os.unlink(tmp_file)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        old_size = volume.size

        try:
            size = int(new_size) * units.Gi
            self._resize(volume, size=size)
        except Exception:
            msg = _('Failed to Extend Volume '
                    '%(volname)s') % {'volname': volume.name}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug("Extend volume from %(old_size)s GB to %(new_size)s GB.",
                  {'old_size': old_size, 'new_size': new_size})

    def manage_existing(self, volume, existing_ref):
        """Manages an existing image.

        Renames the image name to match the expected name for the volume.
        Error checking done by manage_existing_get_size is not repeated.

        :param volume:
            volume ref info to be set
        :param existing_ref:
            existing_ref is a dictionary of the form:
            {'source-name': <name of rbd image>}
        """
        # Raise an exception if we didn't find a suitable rbd image.
        with RADOSClient(self) as client:
            rbd_name = existing_ref['source-name']
            self.RBDProxy().rename(client.ioctx,
                                   utils.convert_str(rbd_name),
                                   utils.convert_str(volume.name))

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of an existing image for manage_existing.

        :param volume:
            volume ref info to be set
        :param existing_ref:
            existing_ref is a dictionary of the form:
            {'source-name': <name of rbd image>}
        """

        # Check that the reference is valid
        if 'source-name' not in existing_ref:
            reason = _('Reference must contain source-name element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)

        rbd_name = utils.convert_str(existing_ref['source-name'])

        with RADOSClient(self) as client:
            # Raise an exception if we didn't find a suitable rbd image.
            try:
                rbd_image = self.rbd.Image(client.ioctx, rbd_name)
            except self.rbd.ImageNotFound:
                kwargs = {'existing_ref': rbd_name,
                          'reason': 'Specified rbd image does not exist.'}
                raise exception.ManageExistingInvalidReference(**kwargs)

            image_size = rbd_image.size()
            rbd_image.close()

            # RBD image size is returned in bytes.  Attempt to parse
            # size as a float and round up to the next integer.
            try:
                convert_size = int(math.ceil(float(image_size) / units.Gi))
                return convert_size
            except ValueError:
                exception_message = (_("Failed to manage existing volume "
                                       "%(name)s, because reported size "
                                       "%(size)s was not a floating-point"
                                       " number.")
                                     % {'name': rbd_name,
                                        'size': image_size})
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

    def _get_image_status(self, image_name):
        args = ['rbd', 'status',
                '--pool', self.configuration.rbd_pool,
                '--format=json',
                image_name]
        args.extend(self._ceph_args())
        out, _ = self._execute(*args)
        return json.loads(out)

    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        manageable_volumes = []
        cinder_ids = [resource['id'] for resource in cinder_volumes]

        with RADOSClient(self) as client:
            for image_name in self.RBDProxy().list(client.ioctx):
                image_id = volume_utils.extract_id_from_volume_name(image_name)
                with RBDVolumeProxy(self, image_name, read_only=True,
                                    client=client.cluster,
                                    ioctx=client.ioctx) as image:
                    try:
                        image_info = {
                            'reference': {'source-name': image_name},
                            'size': int(math.ceil(
                                float(image.size()) / units.Gi)),
                            'cinder_id': None,
                            'extra_info': None
                        }
                        if image_id in cinder_ids:
                            image_info['cinder_id'] = image_id
                            image_info['safe_to_manage'] = False
                            image_info['reason_not_safe'] = 'already managed'
                        elif len(self._get_image_status(
                                image_name)['watchers']) > 0:
                            # If the num of watchers of image is >= 1, then the
                            # image is considered to be used by client(s).
                            image_info['safe_to_manage'] = False
                            image_info['reason_not_safe'] = 'volume in use'
                        elif image_name.endswith('.deleted'):
                            # parent of cloned volume which marked as deleted
                            # should not be manageable.
                            image_info['safe_to_manage'] = False
                            image_info['reason_not_safe'] = (
                                'volume marked as deleted')
                        else:
                            image_info['safe_to_manage'] = True
                            image_info['reason_not_safe'] = None
                        manageable_volumes.append(image_info)
                    except self.rbd.ImageNotFound:
                        LOG.debug("Image %s is not found.", image_name)

        return volume_utils.paginate_entries_list(
            manageable_volumes, marker, limit, offset, sort_keys, sort_dirs)

    def unmanage(self, volume):
        pass

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Return model update from RBD for migrated volume.

        This method should rename the back-end volume name(id) on the
        destination host back to its original name(id) on the source host.

        :param ctxt: The context used to run the method update_migrated_volume
        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :param original_volume_status: The status of the original volume
        :returns: model_update to update DB with any needed changes
        """
        name_id = None
        provider_location = None

        if original_volume_status == 'in-use':
            # The back-end will not be renamed.
            name_id = new_volume['_name_id'] or new_volume['id']
            provider_location = new_volume['provider_location']
            return {'_name_id': name_id,
                    'provider_location': provider_location}

        existing_name = CONF.volume_name_template % new_volume.id
        wanted_name = CONF.volume_name_template % volume.id
        with RADOSClient(self) as client:
            try:
                self.RBDProxy().rename(client.ioctx,
                                       utils.convert_str(existing_name),
                                       utils.convert_str(wanted_name))
            except (self.rbd.ImageNotFound, self.rbd.ImageExists):
                LOG.error('Unable to rename the logical volume '
                          'for volume %s.', volume.id)
                # If the rename fails, _name_id should be set to the new
                # volume id and provider_location should be set to the
                # one from the new volume as well.
                name_id = new_volume._name_id or new_volume.id
                provider_location = new_volume['provider_location']
        return {'_name_id': name_id,
                'provider_location': provider_location}

    def migrate_volume(self, context, volume, host):

        refuse_to_migrate = (False, None)

        if volume.status not in ('available', 'retyping', 'maintenance',
                                 'in-use'):
            LOG.debug('Only available or in-use volumes can be migrated using '
                      'backend assisted migration. Falling back to generic '
                      'migration.')
            return refuse_to_migrate

        if (host['capabilities']['storage_protocol'] != 'ceph'):
            LOG.debug('Source and destination drivers need to be RBD '
                      'to use backend assisted migration. Falling back to '
                      'generic migration.')
            return refuse_to_migrate

        loc_info = host['capabilities'].get('location_info')

        LOG.debug('Attempting RBD assisted volume migration. volume: %(id)s, '
                  'host: %(host)s, status=%(status)s.',
                  {'id': volume.id, 'host': host, 'status': volume.status})

        if not loc_info:
            LOG.debug('Could not find location_info in capabilities reported '
                      'by the destination driver. Falling back to generic '
                      'migration.')
            return refuse_to_migrate

        try:
            (rbd_cluster_name, rbd_ceph_conf, rbd_fsid, rbd_user, rbd_pool) = (
                utils.convert_str(loc_info).split(':'))
        except ValueError:
            LOG.error('Location info needed for backend enabled volume '
                      'migration not in correct format: %s. Falling back to '
                      'generic volume migration.', loc_info)
            return refuse_to_migrate

        with linuxrbd.RBDClient(rbd_user, rbd_pool, conffile=rbd_ceph_conf,
                                rbd_cluster_name=rbd_cluster_name) as target:
            if (rbd_fsid != self._get_fsid()) or \
                    (rbd_fsid != encodeutils.safe_decode(
                        target.client.get_fsid())):
                LOG.info('Migration between clusters is not supported. '
                         'Falling back to generic migration.')
                return refuse_to_migrate

            if rbd_pool == self.configuration.rbd_pool:
                LOG.debug('Migration in the same pool, just need to update '
                          "volume's host value to destination host.")
                return (True, None)

            if volume.status == 'in-use':
                LOG.debug('Migration in-use volume between different pools. '
                          'Falling back to generic migration.')
                return refuse_to_migrate

            with RBDVolumeProxy(self, volume.name, read_only=True) as source:
                try:
                    source.copy(target.ioctx, volume.name)
                except Exception:
                    with excutils.save_and_reraise_exception():
                        LOG.error('Error copying rbd image %(vol)s to target '
                                  'pool %(pool)s.',
                                  {'vol': volume.name, 'pool': rbd_pool})
                        self.RBDProxy().remove(target.ioctx, volume.name)

        try:
            # If the source fails to delete for some reason, we want to leave
            # the target volume in place in case deleting it might cause a lose
            # of data.
            self.delete_volume(volume)
        except Exception:
            reason = 'Failed to delete migration source volume %s.', volume.id
            raise exception.VolumeMigrationFailed(reason=reason)

        LOG.info('Successful RBD assisted volume migration.')

        return (True, None)

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return size of an existing image for manage_existing.

        :param snapshot:
            snapshot ref info to be set
        :param existing_ref:
            existing_ref is a dictionary of the form:
            {'source-name': <name of snapshot>}
        """
        # Check that the reference is valid
        if not isinstance(existing_ref, dict):
            existing_ref = {"source-name": existing_ref}
        if 'source-name' not in existing_ref:
            reason = _('Reference must contain source-name element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)

        volume_name = utils.convert_str(snapshot.volume_name)
        snapshot_name = utils.convert_str(existing_ref['source-name'])

        with RADOSClient(self) as client:
            # Raise an exception if we didn't find a suitable rbd image.
            try:
                rbd_snapshot = self.rbd.Image(client.ioctx, volume_name,
                                              snapshot=snapshot_name)
            except self.rbd.ImageNotFound:
                kwargs = {'existing_ref': snapshot_name,
                          'reason': 'Specified snapshot does not exist.'}
                raise exception.ManageExistingInvalidReference(**kwargs)

            snapshot_size = rbd_snapshot.size()
            rbd_snapshot.close()

            # RBD image size is returned in bytes.  Attempt to parse
            # size as a float and round up to the next integer.
            try:
                convert_size = int(math.ceil(float(snapshot_size) / units.Gi))
                return convert_size
            except ValueError:
                exception_message = (_("Failed to manage existing snapshot "
                                       "%(name)s, because reported size "
                                       "%(size)s was not a floating-point"
                                       " number.")
                                     % {'name': snapshot_name,
                                        'size': snapshot_size})
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Manages an existing snapshot.

        Renames the snapshot name to match the expected name for the snapshot.
        Error checking done by manage_existing_get_size is not repeated.

        :param snapshot:
            snapshot ref info to be set
        :param existing_ref:
            existing_ref is a dictionary of the form:
            {'source-name': <name of rbd snapshot>}
        """
        if not isinstance(existing_ref, dict):
            existing_ref = {"source-name": existing_ref}
        volume_name = utils.convert_str(snapshot.volume_name)
        with RBDVolumeProxy(self, volume_name) as volume:
            snapshot_name = existing_ref['source-name']
            volume.rename_snap(utils.convert_str(snapshot_name),
                               utils.convert_str(snapshot.name))
            if not volume.is_protected_snap(snapshot.name):
                volume.protect_snap(snapshot.name)

    def get_manageable_snapshots(self, cinder_snapshots, marker, limit, offset,
                                 sort_keys, sort_dirs):
        """List manageable snapshots on RBD backend."""
        manageable_snapshots = []
        cinder_snapshot_ids = [resource['id'] for resource in cinder_snapshots]

        with RADOSClient(self) as client:
            for image_name in self.RBDProxy().list(client.ioctx):
                with RBDVolumeProxy(self, image_name, read_only=True,
                                    client=client.cluster,
                                    ioctx=client.ioctx) as image:
                    try:
                        for snapshot in image.list_snaps():
                            snapshot_id = (
                                volume_utils.extract_id_from_snapshot_name(
                                    snapshot['name']))
                            snapshot_info = {
                                'reference': {'source-name': snapshot['name']},
                                'size': int(math.ceil(
                                    float(snapshot['size']) / units.Gi)),
                                'cinder_id': None,
                                'extra_info': None,
                                'safe_to_manage': False,
                                'reason_not_safe': None,
                                'source_reference': {'source-name': image_name}
                            }

                            if snapshot_id in cinder_snapshot_ids:
                                # Exclude snapshots already managed.
                                snapshot_info['reason_not_safe'] = (
                                    'already managed')
                                snapshot_info['cinder_id'] = snapshot_id
                            elif snapshot['name'].endswith('.clone_snap'):
                                # Exclude clone snapshot.
                                snapshot_info['reason_not_safe'] = (
                                    'used for clone snap')
                            elif (snapshot['name'].startswith('backup')
                                  and '.snap.' in snapshot['name']):
                                # Exclude intermediate snapshots created by the
                                # Ceph backup driver.
                                snapshot_info['reason_not_safe'] = (
                                    'used for volume backup')
                            else:
                                snapshot_info['safe_to_manage'] = True
                            manageable_snapshots.append(snapshot_info)
                    except self.rbd.ImageNotFound:
                        LOG.debug("Image %s is not found.", image_name)

        return volume_utils.paginate_entries_list(
            manageable_snapshots, marker, limit, offset, sort_keys, sort_dirs)

    def unmanage_snapshot(self, snapshot):
        """Removes the specified snapshot from Cinder management."""
        with RBDVolumeProxy(self, snapshot.volume_name) as volume:
            volume.set_snap(snapshot.name)
            children = volume.list_children()
            volume.set_snap(None)
            if not children and volume.is_protected_snap(snapshot.name):
                volume.unprotect_snap(snapshot.name)

    def get_backup_device(self, context, backup):
        """Get a backup device from an existing volume.

        To support incremental backups on Ceph to Ceph we don't clone
        the volume.
        """

        if not ('backup.drivers.ceph' in backup.service) or backup.snapshot_id:
            return super(RBDDriver, self).get_backup_device(context, backup)

        volume = objects.Volume.get_by_id(context, backup.volume_id)
        return (volume, False)
