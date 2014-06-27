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

from __future__ import absolute_import
import io
import json
import math
import os
import tempfile
import urllib

from oslo.config import cfg
import six

from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder.openstack.common import fileutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import strutils
from cinder.openstack.common import units
from cinder.volume import driver

try:
    import rados
    import rbd
except ImportError:
    rados = None
    rbd = None


LOG = logging.getLogger(__name__)

rbd_opts = [
    cfg.StrOpt('rbd_pool',
               default='rbd',
               help='The RADOS pool where rbd volumes are stored'),
    cfg.StrOpt('rbd_user',
               default=None,
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
               default=None,
               help='The libvirt uuid of the secret for the rbd_user '
                    'volumes'),
    cfg.StrOpt('volume_tmp_dir',
               default=None,
               help='Directory where temporary image files are stored '
                    'when the volume driver does not write them directly '
                    'to the volume.'),
    cfg.IntOpt('rbd_max_clone_depth',
               default=5,
               help='Maximum number of nested volume clones that are '
                    'taken before a flatten occurs. Set to 0 to disable '
                    'cloning.'),
    cfg.IntOpt('rbd_store_chunk_size', default=4,
               help=_('Volumes will be chunked into objects of this size '
                      '(in megabytes).')),
    cfg.IntOpt('rados_connect_timeout', default=-1,
               help=_('Timeout value (in seconds) used when connecting to '
                      'ceph cluster. If value < 0, no timeout is set and '
                      'default librados value is used.'))
]

CONF = cfg.CONF
CONF.register_opts(rbd_opts)


class RBDImageMetadata(object):
    """RBD image metadata to be used with RBDImageIOWrapper."""
    def __init__(self, image, pool, user, conf):
        self.image = image
        self.pool = strutils.safe_encode(pool)
        self.user = strutils.safe_encode(user)
        self.conf = strutils.safe_encode(conf)


class RBDImageIOWrapper(io.RawIOBase):
    """Enables LibRBD.Image objects to be treated as Python IO objects.

    Calling unimplemented interfaces will raise IOError.
    """

    def __init__(self, rbd_meta):
        super(RBDImageIOWrapper, self).__init__()
        self._rbd_meta = rbd_meta
        self._offset = 0

    def _inc_offset(self, length):
        self._offset += length

    @property
    def rbd_image(self):
        return self._rbd_meta.image

    @property
    def rbd_user(self):
        return self._rbd_meta.user

    @property
    def rbd_pool(self):
        return self._rbd_meta.pool

    @property
    def rbd_conf(self):
        return self._rbd_meta.conf

    def read(self, length=None):
        offset = self._offset
        total = self._rbd_meta.image.size()

        # NOTE(dosaboy): posix files do not barf if you read beyond their
        # length (they just return nothing) but rbd images do so we need to
        # return empty string if we have reached the end of the image.
        if (offset >= total):
            return ''

        if length is None:
            length = total

        if (offset + length) > total:
            length = total - offset

        self._inc_offset(length)
        return self._rbd_meta.image.read(int(offset), int(length))

    def write(self, data):
        self._rbd_meta.image.write(data, self._offset)
        self._inc_offset(len(data))

    def seekable(self):
        return True

    def seek(self, offset, whence=0):
        if whence == 0:
            new_offset = offset
        elif whence == 1:
            new_offset = self._offset + offset
        elif whence == 2:
            new_offset = self._rbd_meta.image.size()
            new_offset += offset
        else:
            raise IOError(_("Invalid argument - whence=%s not supported") %
                          (whence))

        if (new_offset < 0):
            raise IOError(_("Invalid argument"))

        self._offset = new_offset

    def tell(self):
        return self._offset

    def flush(self):
        try:
            self._rbd_meta.image.flush()
        except AttributeError:
            LOG.warning(_("flush() not supported in this version of librbd"))

    def fileno(self):
        """RBD does not have support for fileno() so we raise IOError.

        Raising IOError is recommended way to notify caller that interface is
        not supported - see http://docs.python.org/2/library/io.html#io.IOBase
        """
        raise IOError(_("fileno() not supported by RBD()"))

    # NOTE(dosaboy): if IO object is not closed explicitly, Python auto closes
    # it which, if this is not overridden, calls flush() prior to close which
    # in this case is unwanted since the rbd image may have been closed prior
    # to the autoclean - currently triggering a segfault in librbd.
    def close(self):
        pass


class RBDVolumeProxy(object):
    """Context manager for dealing with an existing rbd volume.

    This handles connecting to rados and opening an ioctx automatically, and
    otherwise acts like a librbd Image object.

    The underlying librados client and ioctx can be accessed as the attributes
    'client' and 'ioctx'.
    """
    def __init__(self, driver, name, pool=None, snapshot=None,
                 read_only=False):
        client, ioctx = driver._connect_to_rados(pool)
        if snapshot is not None:
            snapshot = strutils.safe_encode(snapshot)

        try:
            self.volume = driver.rbd.Image(ioctx, strutils.safe_encode(name),
                                           snapshot=snapshot,
                                           read_only=read_only)
        except driver.rbd.Error:
            LOG.exception(_("error opening rbd image %s"), name)
            driver._disconnect_from_rados(client, ioctx)
            raise
        self.driver = driver
        self.client = client
        self.ioctx = ioctx

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        try:
            self.volume.close()
        finally:
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


class RBDDriver(driver.VolumeDriver):
    """Implements RADOS block device (RBD) volume commands."""

    VERSION = '1.1.0'

    def __init__(self, *args, **kwargs):
        super(RBDDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(rbd_opts)
        self._stats = {}
        # allow overrides for testing
        self.rados = kwargs.get('rados', rados)
        self.rbd = kwargs.get('rbd', rbd)

        # All string args used with librbd must be None or utf-8 otherwise
        # librbd will break.
        for attr in ['rbd_user', 'rbd_ceph_conf', 'rbd_pool']:
            val = getattr(self.configuration, attr)
            if val is not None:
                setattr(self.configuration, attr, strutils.safe_encode(val))

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        if rados is None:
            msg = _('rados and rbd python libraries not found')
            raise exception.VolumeBackendAPIException(data=msg)
        try:
            with RADOSClient(self):
                pass
        except self.rados.Error:
            msg = _('error connecting to ceph cluster')
            LOG.exception(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _ceph_args(self):
        args = []
        if self.configuration.rbd_user:
            args.extend(['--id', self.configuration.rbd_user])
        if self.configuration.rbd_ceph_conf:
            args.extend(['--conf', self.configuration.rbd_ceph_conf])
        return args

    def _connect_to_rados(self, pool=None):
        LOG.debug("opening connection to ceph cluster (timeout=%s)." %
                  (self.configuration.rados_connect_timeout))

        client = self.rados.Rados(rados_id=self.configuration.rbd_user,
                                  conffile=self.configuration.rbd_ceph_conf)
        if pool is not None:
            pool = strutils.safe_encode(pool)
        else:
            pool = self.configuration.rbd_pool

        try:
            if self.configuration.rados_connect_timeout >= 0:
                client.connect(timeout=
                               self.configuration.rados_connect_timeout)
            else:
                client.connect()
            ioctx = client.open_ioctx(pool)
            return client, ioctx
        except self.rados.Error as exc:
            LOG.error("error connecting to ceph cluster.")
            # shutdown cannot raise an exception
            client.shutdown()
            raise exception.VolumeBackendAPIException(data=str(exc))

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

    def _update_volume_stats(self):
        stats = {
            'vendor_name': 'Open Source',
            'driver_version': self.VERSION,
            'storage_protocol': 'ceph',
            'total_capacity_gb': 'unknown',
            'free_capacity_gb': 'unknown',
            'reserved_percentage': 0,
        }
        backend_name = self.configuration.safe_get('volume_backend_name')
        stats['volume_backend_name'] = backend_name or 'RBD'

        try:
            with RADOSClient(self) as client:
                new_stats = client.cluster.get_cluster_stats()
            stats['total_capacity_gb'] = new_stats['kb'] / units.Mi
            stats['free_capacity_gb'] = new_stats['kb_avail'] / units.Mi
        except self.rados.Error:
            # just log and return unknown capacities
            LOG.exception(_('error refreshing volume stats'))
        self._stats = stats

    def get_volume_stats(self, refresh=False):
        """Return the current state of the volume service.

        If 'refresh' is True, run the update first.
        """
        if refresh:
            self._update_volume_stats()
        return self._stats

    def _supports_layering(self):
        return hasattr(self.rbd, 'RBD_FEATURE_LAYERING')

    def _get_clone_depth(self, client, volume_name, depth=0):
        """Returns the number of ancestral clones (if any) of the given volume.
        """
        parent_volume = self.rbd.Image(client.ioctx, volume_name)
        try:
            pool, parent, snap = self._get_clone_info(parent_volume,
                                                      volume_name)
        finally:
            parent_volume.close()

        if not parent:
            return depth

        # If clone depth was reached, flatten should have occurred so if it has
        # been exceeded then something has gone wrong.
        if depth > CONF.rbd_max_clone_depth:
            raise Exception(_("clone depth exceeds limit of %s") %
                            (CONF.rbd_max_clone_depth))

        return self._get_clone_depth(client, parent, depth + 1)

    def create_cloned_volume(self, volume, src_vref):
        """Create a cloned volume from another volume.

        Since we are cloning from a volume and not a snapshot, we must first
        create a snapshot of the source volume.

        The user has the option to limit how long a volume's clone chain can be
        by setting rbd_max_clone_depth. If a clone is made of another clone
        and that clone has rbd_max_clone_depth clones behind it, the source
        volume will be flattened.
        """
        src_name = strutils.safe_encode(src_vref['name'])
        dest_name = strutils.safe_encode(volume['name'])
        flatten_parent = False

        # Do full copy if requested
        if CONF.rbd_max_clone_depth <= 0:
            with RBDVolumeProxy(self, src_name, read_only=True) as vol:
                vol.copy(vol.ioctx, dest_name)

            return

        # Otherwise do COW clone.
        with RADOSClient(self) as client:
            depth = self._get_clone_depth(client, src_name)
            # If source volume is a clone and rbd_max_clone_depth reached,
            # flatten the source before cloning. Zero rbd_max_clone_depth means
            # infinite is allowed.
            if depth == CONF.rbd_max_clone_depth:
                LOG.debug("maximum clone depth (%d) has been reached - "
                          "flattening source volume" %
                          (CONF.rbd_max_clone_depth))
                flatten_parent = True

            src_volume = self.rbd.Image(client.ioctx, src_name)
            try:
                # First flatten source volume if required.
                if flatten_parent:
                    pool, parent, snap = self._get_clone_info(src_volume,
                                                              src_name)
                    # Flatten source volume
                    LOG.debug("flattening source volume %s" % (src_name))
                    src_volume.flatten()
                    # Delete parent clone snap
                    parent_volume = self.rbd.Image(client.ioctx, parent)
                    try:
                        parent_volume.unprotect_snap(snap)
                        parent_volume.remove_snap(snap)
                    finally:
                        parent_volume.close()

                # Create new snapshot of source volume
                clone_snap = "%s.clone_snap" % dest_name
                LOG.debug("creating snapshot='%s'" % (clone_snap))
                src_volume.create_snap(clone_snap)
                src_volume.protect_snap(clone_snap)
            except Exception as exc:
                # Only close if exception since we still need it.
                src_volume.close()
                raise exc

            # Now clone source volume snapshot
            try:
                LOG.debug("cloning '%(src_vol)s@%(src_snap)s' to "
                          "'%(dest)s'" %
                          {'src_vol': src_name, 'src_snap': clone_snap,
                           'dest': dest_name})
                self.rbd.RBD().clone(client.ioctx, src_name, clone_snap,
                                     client.ioctx, dest_name,
                                     features=self.rbd.RBD_FEATURE_LAYERING)
            except Exception as exc:
                src_volume.unprotect_snap(clone_snap)
                src_volume.remove_snap(clone_snap)
                raise exc
            finally:
                src_volume.close()

        LOG.debug("clone created successfully")

    def create_volume(self, volume):
        """Creates a logical volume."""
        if int(volume['size']) == 0:
            size = 100 * units.Mi
        else:
            size = int(volume['size']) * units.Gi

        LOG.debug("creating volume '%s'" % (volume['name']))

        old_format = True
        features = 0
        chunk_size = CONF.rbd_store_chunk_size * units.Mi
        order = int(math.log(chunk_size, 2))
        if self._supports_layering():
            old_format = False
            features = self.rbd.RBD_FEATURE_LAYERING

        with RADOSClient(self) as client:
            self.rbd.RBD().create(client.ioctx,
                                  strutils.safe_encode(volume['name']),
                                  size,
                                  order,
                                  old_format=old_format,
                                  features=features)

    def _flatten(self, pool, volume_name):
        LOG.debug('flattening %(pool)s/%(img)s' %
                  dict(pool=pool, img=volume_name))
        with RBDVolumeProxy(self, volume_name, pool) as vol:
            vol.flatten()

    def _clone(self, volume, src_pool, src_image, src_snap):
        LOG.debug('cloning %(pool)s/%(img)s@%(snap)s to %(dst)s' %
                  dict(pool=src_pool, img=src_image, snap=src_snap,
                       dst=volume['name']))
        with RADOSClient(self, src_pool) as src_client:
            with RADOSClient(self) as dest_client:
                self.rbd.RBD().clone(src_client.ioctx,
                                     strutils.safe_encode(src_image),
                                     strutils.safe_encode(src_snap),
                                     dest_client.ioctx,
                                     strutils.safe_encode(volume['name']),
                                     features=self.rbd.RBD_FEATURE_LAYERING)

    def _resize(self, volume, **kwargs):
        size = kwargs.get('size', None)
        if not size:
            size = int(volume['size']) * units.Gi

        with RBDVolumeProxy(self, volume['name']) as vol:
            vol.resize(size)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self._clone(volume, self.configuration.rbd_pool,
                    snapshot['volume_name'], snapshot['name'])
        if self.configuration.rbd_flatten_volume_from_snapshot:
            self._flatten(self.configuration.rbd_pool, volume['name'])
        if int(volume['size']):
            self._resize(volume)

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
            snap and volume.set_snap(snap)
            pool, parent, parent_snap = tuple(volume.parent_info())
            snap and volume.set_snap(None)
            # Strip the tag off the end of the volume name since it will not be
            # in the snap name.
            if volume_name.endswith('.deleted'):
                volume_name = volume_name[:-len('.deleted')]
            # Now check the snap name matches.
            if parent_snap == "%s.clone_snap" % volume_name:
                return pool, parent, parent_snap
        except self.rbd.ImageNotFound:
            LOG.debug("volume %s is not a clone" % volume_name)
            volume.set_snap(None)

        return (None, None, None)

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

            LOG.debug("deleting parent snapshot %s" % (parent_snap))
            parent_rbd.unprotect_snap(parent_snap)
            parent_rbd.remove_snap(parent_snap)

            parent_has_snaps = bool(list(parent_rbd.list_snaps()))
        finally:
            parent_rbd.close()

        # If parent has been deleted in Cinder, delete the silent reference and
        # keep walking up the chain if it is itself a clone.
        if (not parent_has_snaps) and parent_name.endswith('.deleted'):
            LOG.debug("deleting parent %s" % (parent_name))
            self.rbd.RBD().remove(client.ioctx, parent_name)

            # Now move up to grandparent if there is one
            if g_parent:
                self._delete_clone_parent_refs(client, g_parent, g_parent_snap)

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        # NOTE(dosaboy): this was broken by commit cbe1d5f. Ensure names are
        #                utf-8 otherwise librbd will barf.
        volume_name = strutils.safe_encode(volume['name'])
        with RADOSClient(self) as client:
            try:
                rbd_image = self.rbd.Image(client.ioctx, volume_name)
            except self.rbd.ImageNotFound:
                LOG.info(_("volume %s no longer exists in backend")
                         % (volume_name))
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

                    raise exception.VolumeIsBusy(volume_name=volume_name)

                # Determine if this volume is itself a clone
                pool, parent, parent_snap = self._get_clone_info(rbd_image,
                                                                 volume_name,
                                                                 clone_snap)
            finally:
                rbd_image.close()

            if clone_snap is None:
                LOG.debug("deleting rbd volume %s" % (volume_name))
                try:
                    self.rbd.RBD().remove(client.ioctx, volume_name)
                except self.rbd.ImageBusy:
                    msg = (_("ImageBusy error raised while deleting rbd "
                             "volume. This may have been caused by a "
                             "connection from a client that has crashed and, "
                             "if so, may be resolved by retrying the delete "
                             "after 30 seconds has elapsed."))
                    LOG.warn(msg)
                    # Now raise this so that volume stays available so that we
                    # delete can be retried.
                    raise exception.VolumeIsBusy(msg, volume_name=volume_name)

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
                self.rbd.RBD().rename(client.ioctx, volume_name, new_name)

    def create_snapshot(self, snapshot):
        """Creates an rbd snapshot."""
        with RBDVolumeProxy(self, snapshot['volume_name']) as volume:
            snap = strutils.safe_encode(snapshot['name'])
            volume.create_snap(snap)
            if self._supports_layering():
                volume.protect_snap(snap)

    def delete_snapshot(self, snapshot):
        """Deletes an rbd snapshot."""
        # NOTE(dosaboy): this was broken by commit cbe1d5f. Ensure names are
        #                utf-8 otherwise librbd will barf.
        volume_name = strutils.safe_encode(snapshot['volume_name'])
        snap_name = strutils.safe_encode(snapshot['name'])
        with RBDVolumeProxy(self, volume_name) as volume:
            if self._supports_layering():
                try:
                    volume.unprotect_snap(snap_name)
                except self.rbd.ImageBusy:
                    raise exception.SnapshotIsBusy(snapshot_name=snap_name)
            volume.remove_snap(snap_name)

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        pass

    def create_export(self, context, volume):
        """Exports the volume."""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass

    def initialize_connection(self, volume, connector):
        hosts, ports = self._get_mon_addrs()
        data = {
            'driver_volume_type': 'rbd',
            'data': {
                'name': '%s/%s' % (self.configuration.rbd_pool,
                                   volume['name']),
                'hosts': hosts,
                'ports': ports,
                'auth_enabled': (self.configuration.rbd_user is not None),
                'auth_username': self.configuration.rbd_user,
                'secret_type': 'ceph',
                'secret_uuid': self.configuration.rbd_secret_uuid, }
        }
        LOG.debug('connection data: %s', data)
        return data

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def _parse_location(self, location):
        prefix = 'rbd://'
        if not location.startswith(prefix):
            reason = _('Not stored in rbd')
            raise exception.ImageUnacceptable(image_id=location, reason=reason)
        pieces = map(urllib.unquote, location[len(prefix):].split('/'))
        if any(map(lambda p: p == '', pieces)):
            reason = _('Blank components')
            raise exception.ImageUnacceptable(image_id=location, reason=reason)
        if len(pieces) != 4:
            reason = _('Not an rbd snapshot')
            raise exception.ImageUnacceptable(image_id=location, reason=reason)
        return pieces

    def _get_fsid(self):
        with RADOSClient(self) as client:
            return client.cluster.get_fsid()

    def _is_cloneable(self, image_location, image_meta):
        try:
            fsid, pool, image, snapshot = self._parse_location(image_location)
        except exception.ImageUnacceptable as e:
            LOG.debug('not cloneable: %s', six.text_type(e))
            return False

        if self._get_fsid() != fsid:
            reason = ('%s is in a different ceph cluster') % image_location
            LOG.debug(reason)
            return False

        if image_meta['disk_format'] != 'raw':
            reason = ("rbd image clone requires image format to be "
                      "'raw' but image {0} is '{1}'").format(
                          image_location, image_meta['disk_format'])
            LOG.debug(reason)
            return False

        # check that we can read the image
        try:
            with RBDVolumeProxy(self, image,
                                pool=pool,
                                snapshot=snapshot,
                                read_only=True):
                return True
        except self.rbd.Error as e:
            LOG.debug('Unable to open image %(loc)s: %(err)s' %
                      dict(loc=image_location, err=e))
            return False

    def clone_image(self, volume, image_location, image_id, image_meta):
        image_location = image_location[0] if image_location else None
        if image_location is None or not self._is_cloneable(
                image_location, image_meta):
            return ({}, False)
        prefix, pool, image, snapshot = self._parse_location(image_location)
        self._clone(volume, pool, image, snapshot)
        self._resize(volume)
        return {'provider_location': None}, True

    def _ensure_tmp_exists(self):
        tmp_dir = self.configuration.volume_tmp_dir
        if tmp_dir and not os.path.exists(tmp_dir):
            os.makedirs(tmp_dir)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        self._ensure_tmp_exists()
        tmp_dir = self.configuration.volume_tmp_dir

        with tempfile.NamedTemporaryFile(dir=tmp_dir) as tmp:
            image_utils.fetch_to_raw(context, image_service, image_id,
                                     tmp.name,
                                     self.configuration.volume_dd_blocksize,
                                     size=volume['size'])

            self.delete_volume(volume)

            chunk_size = CONF.rbd_store_chunk_size * units.Mi
            order = int(math.log(chunk_size, 2))
            # keep using the command line import instead of librbd since it
            # detects zeroes to preserve sparseness in the image
            args = ['rbd', 'import',
                    '--pool', self.configuration.rbd_pool,
                    '--order', order,
                    tmp.name, volume['name']]
            if self._supports_layering():
                args.append('--new-format')
            args.extend(self._ceph_args())
            self._try_execute(*args)
        self._resize(volume)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        self._ensure_tmp_exists()

        tmp_dir = self.configuration.volume_tmp_dir or '/tmp'
        tmp_file = os.path.join(tmp_dir,
                                volume['name'] + '-' + image_meta['id'])
        with fileutils.remove_path_on_error(tmp_file):
            args = ['rbd', 'export',
                    '--pool', self.configuration.rbd_pool,
                    volume['name'], tmp_file]
            args.extend(self._ceph_args())
            self._try_execute(*args)
            image_utils.upload_volume(context, image_service,
                                      image_meta, tmp_file)
        os.unlink(tmp_file)

    def backup_volume(self, context, backup, backup_service):
        """Create a new backup from an existing volume."""
        volume = self.db.volume_get(context, backup['volume_id'])

        with RBDVolumeProxy(self, volume['name'],
                            self.configuration.rbd_pool) as rbd_image:
            rbd_meta = RBDImageMetadata(rbd_image, self.configuration.rbd_pool,
                                        self.configuration.rbd_user,
                                        self.configuration.rbd_ceph_conf)
            rbd_fd = RBDImageIOWrapper(rbd_meta)
            backup_service.backup(backup, rbd_fd)

        LOG.debug("volume backup complete.")

    def restore_backup(self, context, backup, volume, backup_service):
        """Restore an existing backup to a new or existing volume."""
        with RBDVolumeProxy(self, volume['name'],
                            self.configuration.rbd_pool) as rbd_image:
            rbd_meta = RBDImageMetadata(rbd_image, self.configuration.rbd_pool,
                                        self.configuration.rbd_user,
                                        self.configuration.rbd_ceph_conf)
            rbd_fd = RBDImageIOWrapper(rbd_meta)
            backup_service.restore(backup, volume['id'], rbd_fd)

        LOG.debug("volume restore complete.")

    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        old_size = volume['size']

        try:
            size = int(new_size) * units.Gi
            self._resize(volume, size=size)
        except Exception:
            msg = _('Failed to Extend Volume '
                    '%(volname)s') % {'volname': volume['name']}
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
            self.rbd.RBD().rename(client.ioctx, strutils.safe_encode(rbd_name),
                                  strutils.safe_encode(volume['name']))

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

        rbd_name = strutils.safe_encode(existing_ref['source-name'])

        with RADOSClient(self) as client:
            # Raise an exception if we didn't find a suitable rbd image.
            try:
                rbd_image = self.rbd.Image(client.ioctx, rbd_name)
                image_size = rbd_image.size()
            except self.rbd.ImageNotFound:
                kwargs = {'existing_ref': rbd_name,
                          'reason': 'Specified rbd image does not exist.'}
                raise exception.ManageExistingInvalidReference(**kwargs)
            finally:
                rbd_image.close()

            # RBD image size is returned in bytes.  Attempt to parse
            # size as a float and round up to the next integer.
            try:
                convert_size = int(math.ceil(int(image_size))) / units.Gi
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
