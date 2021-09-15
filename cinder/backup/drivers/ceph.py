# Copyright 2013 Canonical Ltd.
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

"""Ceph Backup Service Implementation.

This driver supports backing up volumes of any type to a Ceph object store. It
is also capable of detecting whether the volume to be backed up is a Ceph RBD
volume and, if so, attempts to perform incremental/differential backups.

Support is also included for the following in the case of a source volume being
a Ceph RBD volume:

    * backing up within the same Ceph pool (not recommended)
    * backing up between different Ceph pools
    * backing up between different Ceph clusters

At the time of writing, differential backup support in Ceph/librbd was quite
new so this driver accounts for this by first attempting differential backup
and falling back to full backup/copy if the former fails. It is recommended
that you upgrade to Ceph Dumpling (>= v0.67) or above to get the best results.

If incremental backups are used, multiple backups of the same volume are stored
as snapshots so that minimal space is consumed in the object store and
restoring the volume takes a far reduced amount of time compared to a full
copy.

Note that Cinder supports restoring to a new volume or the original volume the
backup was taken from. For the latter case, a full copy is enforced since this
was deemed the safest action to take. It is therefore recommended to always
restore to a new volume (default).
"""

import fcntl
import json
import os
import re
import subprocess
import time

import eventlet
from os_brick.initiator import linuxrbd
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder.backup import driver
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
import cinder.volume.drivers.rbd as rbd_driver

try:
    import rados
    import rbd
except ImportError:
    rados = None
    rbd = None

LOG = logging.getLogger(__name__)

service_opts = [
    cfg.StrOpt('backup_ceph_conf', default='/etc/ceph/ceph.conf',
               help='Ceph configuration file to use.'),
    cfg.StrOpt('backup_ceph_user', default='cinder',
               help='The Ceph user to connect with. Default here is to use '
                    'the same user as for Cinder volumes. If not using cephx '
                    'this should be set to None.'),
    cfg.IntOpt('backup_ceph_chunk_size', default=(units.Mi * 128),
               help='The chunk size, in bytes, that a backup is broken into '
                    'before transfer to the Ceph object store.'),
    cfg.StrOpt('backup_ceph_pool', default='backups',
               help='The Ceph pool where volume backups are stored.'),
    cfg.IntOpt('backup_ceph_stripe_unit', default=0,
               help='RBD stripe unit to use when creating a backup image.'),
    cfg.IntOpt('backup_ceph_stripe_count', default=0,
               help='RBD stripe count to use when creating a backup image.'),
    cfg.BoolOpt('backup_ceph_image_journals', default=False,
                help='If True, apply JOURNALING and EXCLUSIVE_LOCK feature '
                     'bits to the backup RBD objects to allow mirroring'),
    cfg.BoolOpt('restore_discard_excess_bytes', default=True,
                help='If True, always discard excess bytes when restoring '
                     'volumes i.e. pad with zeroes.')
]

CONF = cfg.CONF
CONF.register_opts(service_opts)


class VolumeMetadataBackup(object):

    def __init__(self, client, backup_id):
        self._client = client
        self._backup_id = backup_id

    @property
    def name(self):
        return utils.convert_str("backup.%s.meta" % self._backup_id)

    @property
    def exists(self):
        meta_obj = eventlet.tpool.Proxy(rados.Object(self._client.ioctx,
                                                     self.name))
        return self._exists(meta_obj)

    def _exists(self, obj):
        try:
            obj.stat()
        except rados.ObjectNotFound:
            return False
        else:
            return True

    def set(self, json_meta):
        """Write JSON metadata to a new object.

        This should only be called once per backup. Raises
        VolumeMetadataBackupExists if the object already exists.
        """
        meta_obj = eventlet.tpool.Proxy(rados.Object(self._client.ioctx,
                                                     self.name))
        if self._exists(meta_obj):
            msg = _("Metadata backup object '%s' already exists") % self.name
            raise exception.VolumeMetadataBackupExists(msg)

        meta_obj.write(json_meta.encode('utf-8'))

    def get(self):
        """Get metadata backup object.

        Returns None if the object does not exist.
        """
        meta_obj = eventlet.tpool.Proxy(rados.Object(self._client.ioctx,
                                                     self.name))
        if not self._exists(meta_obj):
            LOG.debug("Metadata backup object %s does not exist", self.name)
            return None

        return meta_obj.read().decode('utf-8')

    def remove_if_exists(self):
        meta_obj = eventlet.tpool.Proxy(rados.Object(self._client.ioctx,
                                                     self.name))
        try:
            meta_obj.remove()
        except rados.ObjectNotFound:
            LOG.debug("Metadata backup object '%s' not found - ignoring",
                      self.name)


@interface.backupdriver
class CephBackupDriver(driver.BackupDriver):
    """Backup Cinder volumes to Ceph Object Store.

    This class enables backing up Cinder volumes to a Ceph object store.
    Backups may be stored in their own pool or even cluster. Store location is
    defined by the Ceph conf file and service config options supplied.

    If the source volume is itself an RBD volume, the backup will be performed
    using incremental differential backups which *should* give a performance
    gain.
    """

    def __init__(self, context, execute=None):
        super().__init__(context)
        self.rbd = rbd
        self.rados = rados
        self.chunk_size = CONF.backup_ceph_chunk_size
        self._execute = execute or utils.execute

        if self._supports_stripingv2:
            self.rbd_stripe_unit = CONF.backup_ceph_stripe_unit
            self.rbd_stripe_count = CONF.backup_ceph_stripe_count
        else:
            LOG.info("RBD striping not supported - ignoring configuration "
                     "settings for rbd striping.")
            self.rbd_stripe_count = 0
            self.rbd_stripe_unit = 0

        self._ceph_backup_user = utils.convert_str(CONF.backup_ceph_user)
        self._ceph_backup_pool = utils.convert_str(CONF.backup_ceph_pool)
        self._ceph_backup_conf = utils.convert_str(CONF.backup_ceph_conf)

    @staticmethod
    def get_driver_options():
        return service_opts

    def _validate_string_args(self, *args):
        """Ensure all args are non-None and non-empty."""
        return all(args)

    def _ceph_args(self, user, conf=None, pool=None):
        """Create default ceph args for executing rbd commands.

        If no --conf is provided, rbd will look in the default locations e.g.
        /etc/ceph/ceph.conf
        """

        # Make sure user arg is valid since rbd command may not fail if
        # invalid/no user provided, resulting in unexpected behaviour.
        if not self._validate_string_args(user):
            raise exception.BackupInvalidCephArgs(_("invalid user '%s'") %
                                                  user)

        args = ['--id', user]
        if conf:
            args.extend(['--conf', conf])
        if pool:
            args.extend(['--pool', pool])

        return args

    @property
    def _supports_layering(self):
        """Determine if copy-on-write is supported by our version of librbd."""
        return hasattr(self.rbd, 'RBD_FEATURE_LAYERING')

    @property
    def _supports_stripingv2(self):
        """Determine if striping is supported by our version of librbd."""
        return hasattr(self.rbd, 'RBD_FEATURE_STRIPINGV2')

    @property
    def _supports_exclusive_lock(self):
        """Determine if exclusive-lock is supported by librbd."""
        return hasattr(self.rbd, 'RBD_FEATURE_EXCLUSIVE_LOCK')

    @property
    def _supports_journaling(self):
        """Determine if journaling is supported by our version of librbd."""
        return hasattr(self.rbd, 'RBD_FEATURE_JOURNALING')

    @property
    def _supports_fast_diff(self):
        """Determine if fast-diff is supported by our version of librbd."""
        return hasattr(self.rbd, 'RBD_FEATURE_FAST_DIFF')

    def _get_rbd_support(self):
        """Determine RBD features supported by our version of librbd."""
        old_format = True
        features = 0
        if self._supports_layering:
            old_format = False
            features |= self.rbd.RBD_FEATURE_LAYERING
        if self._supports_stripingv2:
            old_format = False
            features |= self.rbd.RBD_FEATURE_STRIPINGV2

        if CONF.backup_ceph_image_journals:
            LOG.debug("RBD journaling supported by backend and requested "
                      "via config. Enabling it together with "
                      "exclusive-lock")
            old_format = False
            features |= (self.rbd.RBD_FEATURE_EXCLUSIVE_LOCK |
                         self.rbd.RBD_FEATURE_JOURNALING)

        # NOTE(christian_rohmann): Check for fast-diff support and enable it
        if self._supports_fast_diff:
            LOG.debug("RBD also supports fast-diff, enabling it "
                      "together with exclusive-lock and object-map")
            old_format = False
            features |= (self.rbd.RBD_FEATURE_EXCLUSIVE_LOCK |
                         self.rbd.RBD_FEATURE_OBJECT_MAP |
                         self.rbd.RBD_FEATURE_FAST_DIFF)

        return (old_format, features)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        if rados is None or rbd is None:
            msg = _('rados and rbd python libraries not found')
            raise exception.BackupDriverException(reason=msg)

        for attr in ['backup_ceph_user', 'backup_ceph_pool',
                     'backup_ceph_conf']:
            val = getattr(CONF, attr)
            if not val:
                raise exception.InvalidConfigurationValue(option=attr,
                                                          value=val)
        # NOTE: Checking connection to ceph
        # RADOSClient __init__ method invokes _connect_to_rados
        # so no need to check for self.rados.Error here.
        with rbd_driver.RADOSClient(self, self._ceph_backup_pool):
            pass

        # NOTE(christian_rohmann): Check features required for journaling
        if CONF.backup_ceph_image_journals:
            if not self._supports_exclusive_lock and self._supports_journaling:
                LOG.error("RBD journaling not supported - unable to "
                          "support per image mirroring in backup pool")
                raise exception.BackupInvalidCephArgs(
                    _("Image Journaling set but RBD backend does "
                      "not support journaling")
                )

    def _connect_to_rados(self, pool=None):
        """Establish connection to the backup Ceph cluster."""
        client = eventlet.tpool.Proxy(self.rados.Rados(
                                      rados_id=self._ceph_backup_user,
                                      conffile=self._ceph_backup_conf))
        try:
            client.connect()
            pool_to_open = utils.convert_str(pool or self._ceph_backup_pool)
            ioctx = client.open_ioctx(pool_to_open)
            return client, ioctx
        except self.rados.Error:
            # shutdown cannot raise an exception
            client.shutdown()
            raise

    def _disconnect_from_rados(self, client, ioctx):
        """Terminate connection with the backup Ceph cluster."""
        # closing an ioctx cannot raise an exception
        ioctx.close()
        client.shutdown()

    def _format_base_name(self, service_metadata):
        base_name = json.loads(service_metadata)["base"]
        return utils.convert_str(base_name)

    def _get_backup_base_name(self, volume_id, backup=None):
        """Return name of base image used for backup.

        Incremental backups use a new base name so we support old and new style
        format.
        """
        # Ensure no unicode
        if not backup:
            return utils.convert_str("volume-%s.backup.base" % volume_id)

        if backup.service_metadata:
            return self._format_base_name(backup.service_metadata)

        # 'parent' field will only be present in incremental backups. This is
        # filled by cinder-api
        if backup.parent:
            # Old backups don't have the base name in the service_metadata,
            # so we use the default RBD backup base
            if backup.parent.service_metadata:
                service_metadata = backup.parent.service_metadata
                base_name = self._format_base_name(service_metadata)
            else:
                base_name = utils.convert_str("volume-%s.backup.base"
                                              % volume_id)

            return base_name

        return utils.convert_str("volume-%s.backup.%s"
                                 % (volume_id, backup.id))

    def _discard_bytes(self, volume, offset, length):
        """Trim length bytes from offset.

        If the volume is an rbd do a discard() otherwise assume it is a file
        and pad with zeroes.
        """
        if length:
            LOG.debug("Discarding %(length)s bytes from offset %(offset)s",
                      {'length': length, 'offset': offset})
            if self._file_is_rbd(volume):
                limit = 2 * units.Gi - 1
                chunks = int(length / limit)
                for chunk in range(0, chunks):
                    eventlet.tpool.Proxy(volume.rbd_image).discard(
                        offset + chunk * limit, limit)
                rem = int(length % limit)
                if rem:
                    eventlet.tpool.Proxy(volume.rbd_image).discard(
                        offset + chunks * limit, rem)
            else:
                zeroes = '\0' * self.chunk_size
                chunks = int(length / self.chunk_size)
                for chunk in range(0, chunks):
                    LOG.debug("Writing zeroes chunk %d", chunk)
                    volume.write(zeroes)
                    volume.flush()

                rem = int(length % self.chunk_size)
                if rem:
                    zeroes = '\0' * rem
                    volume.write(zeroes)
                    volume.flush()

    def _transfer_data(self, src, src_name, dest, dest_name, length):
        """Transfer data between files (Python IO objects)."""
        LOG.debug("Transferring data between '%(src)s' and '%(dest)s'",
                  {'src': src_name, 'dest': dest_name})

        chunks = int(length / self.chunk_size)
        LOG.debug("%(chunks)s chunks of %(bytes)s bytes to be transferred",
                  {'chunks': chunks, 'bytes': self.chunk_size})

        for chunk in range(0, chunks):
            before = time.time()
            data = src.read(self.chunk_size)
            # If we have reach end of source, discard any extraneous bytes from
            # destination volume if trim is enabled and stop writing.
            if data == b'':
                if CONF.restore_discard_excess_bytes:
                    self._discard_bytes(dest, dest.tell(),
                                        length - dest.tell())

                return

            dest.write(data)
            dest.flush()
            delta = (time.time() - before)
            rate = (self.chunk_size / delta) / 1024
            LOG.debug("Transferred chunk %(chunk)s of %(chunks)s "
                      "(%(rate)dK/s)",
                      {'chunk': chunk + 1,
                       'chunks': chunks,
                       'rate': rate})

        rem = int(length % self.chunk_size)
        if rem:
            LOG.debug("Transferring remaining %s bytes", rem)
            data = src.read(rem)
            if data == b'':
                if CONF.restore_discard_excess_bytes:
                    self._discard_bytes(dest, dest.tell(), rem)
            else:
                dest.write(data)
                dest.flush()

    def _create_base_image(self, name, size, rados_client):
        """Create a base backup image.

        This will be the base image used for storing differential exports.
        """
        LOG.debug("Creating base image '%s'", name)
        old_format, features = self._get_rbd_support()
        eventlet.tpool.Proxy(self.rbd.RBD()).create(
            ioctx=rados_client.ioctx,
            name=name,
            size=size,
            old_format=old_format,
            features=features,
            stripe_unit=self.rbd_stripe_unit,
            stripe_count=self.rbd_stripe_count)

    def _delete_backup_snapshot(self, rados_client, base_name, backup_id):
        """Delete snapshot associated with this backup if one exists.

        A backup should have at most ONE associated snapshot.

        This is required before attempting to delete the base image. The
        snapshot on the original volume can be left as it will be purged when
        the volume is deleted.

        Returns tuple(deleted_snap_name, num_of_remaining_snaps).
        """
        remaining_snaps = 0
        base_rbd = eventlet.tpool.Proxy(self.rbd.Image(rados_client.ioctx,
                                                       base_name))
        try:
            snap_name = self._get_backup_snap_name(base_rbd, base_name,
                                                   backup_id)
            if snap_name:
                LOG.debug("Deleting backup snapshot='%s'", snap_name)
                base_rbd.remove_snap(snap_name)
            else:
                LOG.debug("No backup snapshot to delete")

            # Now check whether any snapshots remain on the base image
            backup_snaps = self.get_backup_snaps(base_rbd)
            if backup_snaps:
                remaining_snaps = len(backup_snaps)
        finally:
            base_rbd.close()

        return snap_name, remaining_snaps

    def _try_delete_base_image(self, backup, base_name=None):
        """Try to delete backup RBD image.

        If the rbd image is a base image for incremental backups, it may have
        snapshots. Delete the snapshot associated with backup_id and if the
        image has no more snapshots, delete it. Otherwise return.

        If no base name is provided try normal (full) format then diff format
        image name.

        If a base name is provided but does not exist, ImageNotFound will be
        raised.

        If the image is busy, a number of retries will be performed if
        ImageBusy is received, after which the exception will be propagated to
        the caller.
        """
        retries = 3
        delay = 5
        try_diff_format = False
        volume_id = backup.volume_id

        if base_name is None:
            try_diff_format = True

            base_name = self._get_backup_base_name(volume_id, backup=backup)
            LOG.debug("Trying diff format basename='%(basename)s' for "
                      "backup base image of volume %(volume)s.",
                      {'basename': base_name, 'volume': volume_id})

        with eventlet.tpool.Proxy(rbd_driver.RADOSClient(self,
                                  backup.container)) as client:
            rbd_exists, base_name = \
                self._rbd_image_exists(base_name, volume_id, client,
                                       try_diff_format=try_diff_format)
            if not rbd_exists:
                raise self.rbd.ImageNotFound(_("image %s not found") %
                                             base_name)

            while retries >= 0:
                # First delete associated snapshot from base image (if exists)
                snap, rem = self._delete_backup_snapshot(client, base_name,
                                                         backup.id)
                if rem:
                    LOG.info(
                        "Backup base image of volume %(volume)s still "
                        "has %(snapshots)s snapshots so skipping base "
                        "image delete.",
                        {'snapshots': rem, 'volume': volume_id})
                    return

                LOG.info("Deleting backup base image='%(basename)s' of "
                         "volume %(volume)s.",
                         {'basename': base_name, 'volume': volume_id})
                # Delete base if no more snapshots
                try:
                    eventlet.tpool.Proxy(self.rbd.RBD()).remove(
                        client.ioctx, base_name)
                except self.rbd.ImageBusy:
                    # Allow a retry if the image is busy
                    if retries > 0:
                        LOG.info("Backup image of volume %(volume)s is "
                                 "busy, retrying %(retries)s more time(s) "
                                 "in %(delay)ss.",
                                 {'retries': retries,
                                  'delay': delay,
                                  'volume': volume_id})
                    else:
                        LOG.error("Max retries reached deleting backup "
                                  "%(basename)s image of volume %(volume)s.",
                                  {'volume': volume_id,
                                   'basename': base_name})
                        raise
                else:
                    LOG.debug("Base backup image='%(basename)s' of volume "
                              "%(volume)s deleted.",
                              {'basename': base_name, 'volume': volume_id})
                    retries = 0
                finally:
                    retries -= 1

            # Since we have deleted the base image we can delete the source
            # volume backup snapshot.
            src_name = utils.convert_str(volume_id)
            if src_name in eventlet.tpool.Proxy(
                    self.rbd.RBD()).list(client.ioctx):
                LOG.debug("Deleting source volume snapshot '%(snapshot)s' "
                          "for backup %(basename)s.",
                          {'snapshot': snap, 'basename': base_name})
                src_rbd = eventlet.tpool.Proxy(self.rbd.Image(client.ioctx,
                                                              src_name))
                try:
                    src_rbd.remove_snap(snap)
                finally:
                    src_rbd.close()

    def _piped_execute(self, cmd1, cmd2):
        """Pipe output of cmd1 into cmd2."""
        LOG.debug("Piping cmd1='%s' into...", ' '.join(cmd1))
        LOG.debug("cmd2='%s'", ' '.join(cmd2))

        try:
            p1 = subprocess.Popen(cmd1, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  close_fds=True)
        except OSError as e:
            LOG.error("Pipe1 failed - %s ", e)
            raise

        # NOTE(dosaboy): ensure that the pipe is blocking. This is to work
        # around the case where evenlet.green.subprocess is used which seems to
        # use a non-blocking pipe.
        flags = fcntl.fcntl(p1.stdout, fcntl.F_GETFL) & (~os.O_NONBLOCK)
        fcntl.fcntl(p1.stdout, fcntl.F_SETFL, flags)

        try:
            p2 = subprocess.Popen(cmd2, stdin=p1.stdout,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  close_fds=True)
        except OSError as e:
            LOG.error("Pipe2 failed - %s ", e)
            raise

        p1.stdout.close()
        stdout, stderr = p2.communicate()
        return p2.returncode, stderr

    def _rbd_diff_transfer(self, src_name, src_pool, dest_name, dest_pool,
                           src_user, src_conf, dest_user, dest_conf,
                           src_snap=None, from_snap=None):
        """Copy only extents changed between two points.

        If no snapshot is provided, the diff extents will be all those changed
        since the rbd volume/base was created, otherwise it will be those
        changed since the snapshot was created.
        """
        LOG.debug("Performing differential transfer from '%(src)s' to "
                  "'%(dest)s'",
                  {'src': src_name, 'dest': dest_name})

        # NOTE(dosaboy): Need to be tolerant of clusters/clients that do
        # not support these operations since at the time of writing they
        # were very new.

        src_ceph_args = self._ceph_args(src_user, src_conf, pool=src_pool)
        dest_ceph_args = self._ceph_args(dest_user, dest_conf, pool=dest_pool)

        cmd1 = ['rbd', 'export-diff'] + src_ceph_args
        if from_snap is not None:
            cmd1.extend(['--from-snap', from_snap])
        if src_snap:
            path = utils.convert_str("%s/%s@%s"
                                     % (src_pool, src_name, src_snap))
        else:
            path = utils.convert_str("%s/%s" % (src_pool, src_name))
        cmd1.extend([path, '-'])

        cmd2 = ['rbd', 'import-diff'] + dest_ceph_args
        rbd_path = utils.convert_str("%s/%s" % (dest_pool, dest_name))
        cmd2.extend(['-', rbd_path])

        ret, stderr = self._piped_execute(cmd1, cmd2)
        if ret:
            msg = (_("RBD diff op failed - (ret=%(ret)s stderr=%(stderr)s)") %
                   {'ret': ret, 'stderr': stderr})
            LOG.info(msg)
            raise exception.BackupRBDOperationFailed(msg)

    def _rbd_image_exists(self, name, volume_id, client,
                          try_diff_format=False):
        """Return tuple (exists, name)."""
        rbds = eventlet.tpool.Proxy(self.rbd.RBD()).list(client.ioctx)
        if name not in rbds:
            LOG.debug("Image '%s' not found - trying diff format name", name)
            if try_diff_format:
                name = self._get_backup_base_name(volume_id)
                if name not in rbds:
                    LOG.debug("Diff format image '%s' not found", name)
                    return False, name
            else:
                return False, name

        return True, name

    def _snap_exists(self, base_name, snap_name, client):
        """Return True if snapshot exists in base image."""
        base_rbd = eventlet.tpool.Proxy(self.rbd.Image(client.ioctx,
                                        base_name, read_only=True))
        try:
            snaps = base_rbd.list_snaps()

            if snaps is None:
                return False

            for snap in snaps:
                if snap['name'] == snap_name:
                    return True
        finally:
            base_rbd.close()

        return False

    def _full_rbd_backup(self, container, base_name, length):
        """Create the base_image for a full RBD backup."""
        with eventlet.tpool.Proxy(rbd_driver.RADOSClient(self,
                                  container)) as client:
            self._create_base_image(base_name, length, client)
        # Now we just need to return from_snap=None and image_created=True, if
        # there is some exception in making backup snapshot, will clean up the
        # base image.
        return None, True

    def _incremental_rbd_backup(self, backup, base_name, length,
                                source_rbd_image, volume_id):
        """Select the last snapshot for a RBD incremental backup."""

        container = backup.container
        last_incr = backup.parent_id
        LOG.debug("Trying to perform an incremental backup with container: "
                  "%(container)s, base_name: %(base)s, source RBD image: "
                  "%(source)s, volume ID %(volume)s and last incremental "
                  "backup ID: %(incr)s.",
                  {'container': container,
                   'base': base_name,
                   'source': source_rbd_image,
                   'volume': volume_id,
                   'incr': last_incr,
                   })

        with eventlet.tpool.Proxy(rbd_driver.RADOSClient(self,
                                  container)) as client:
            base_rbd = eventlet.tpool.Proxy(self.rbd.Image(client.ioctx,
                                                           base_name,
                                                           read_only=True))
            try:
                from_snap = self._get_backup_snap_name(base_rbd,
                                                       base_name,
                                                       last_incr)
                if from_snap is None:
                    msg = (_(
                        "Can't find snapshot from parent %(incr)s and "
                        "base name image %(base)s.") %
                        {'incr': last_incr, 'base': base_name})
                    LOG.error(msg)
                    raise exception.BackupRBDOperationFailed(msg)
            finally:
                base_rbd.close()

        return from_snap, False

    def _backup_rbd(self, backup, volume_file, volume_name, length):
        """Create an incremental or full backup from an RBD image."""
        rbd_user = volume_file.rbd_user
        rbd_pool = volume_file.rbd_pool
        rbd_conf = volume_file.rbd_conf
        source_rbd_image = eventlet.tpool.Proxy(volume_file.rbd_image)
        volume_id = backup.volume_id
        base_name = None

        # If backup.parent_id is None performs full RBD backup
        if backup.parent_id is None:
            base_name = self._get_backup_base_name(volume_id, backup=backup)
            from_snap, image_created = self._full_rbd_backup(backup.container,
                                                             base_name,
                                                             length)
        # Otherwise performs incremental rbd backup
        else:
            # Find the base name from the parent backup's service_metadata
            base_name = self._get_backup_base_name(volume_id, backup=backup)
            rbd_img = source_rbd_image
            from_snap, image_created = self._incremental_rbd_backup(backup,
                                                                    base_name,
                                                                    length,
                                                                    rbd_img,
                                                                    volume_id)

        LOG.debug("Using --from-snap '%(snap)s' for incremental backup of "
                  "volume %(volume)s.",
                  {'snap': from_snap, 'volume': volume_id})

        # Snapshot source volume so that we have a new point-in-time
        new_snap = self._get_new_snap_name(backup.id)
        LOG.debug("Creating backup snapshot='%s'", new_snap)
        source_rbd_image.create_snap(new_snap)

        # Attempt differential backup. If this fails, perhaps because librbd
        # or Ceph cluster version does not support it, do a full backup
        # instead.
        #
        # TODO(dosaboy): find a way to determine if the operation is supported
        #                rather than brute force approach.
        try:
            before = time.time()
            self._rbd_diff_transfer(volume_name, rbd_pool, base_name,
                                    backup.container,
                                    src_user=rbd_user,
                                    src_conf=rbd_conf,
                                    dest_user=self._ceph_backup_user,
                                    dest_conf=self._ceph_backup_conf,
                                    src_snap=new_snap,
                                    from_snap=from_snap)

            LOG.debug("Differential backup transfer completed in %.4fs",
                      (time.time() - before))

        except exception.BackupRBDOperationFailed:
            with excutils.save_and_reraise_exception():
                LOG.debug("Differential backup transfer failed")

                # Clean up if image was created as part of this operation
                if image_created:
                    self._try_delete_base_image(backup, base_name=base_name)

                # Delete snapshot
                LOG.debug("Deleting diff backup snapshot='%(snapshot)s' of "
                          "source volume='%(volume)s'.",
                          {'snapshot': new_snap, 'volume': volume_id})
                source_rbd_image.remove_snap(new_snap)

        return {'service_metadata': '{"base": "%s"}' % base_name}

    def _file_is_rbd(self, volume_file):
        """Returns True if the volume_file is actually an RBD image."""
        return hasattr(volume_file, 'rbd_image')

    def _full_backup(self, backup, src_volume, src_name, length):
        """Perform a full backup of src volume.

        First creates a base backup image in our backup location then performs
        an chunked copy of all data from source volume to a new backup rbd
        image.
        """
        volume_id = backup.volume_id
        if backup.snapshot_id:
            backup_name = self._get_backup_base_name(volume_id)
        else:
            backup_name = self._get_backup_base_name(volume_id, backup=backup)

        with eventlet.tpool.Proxy(rbd_driver.RADOSClient(self,
                                  backup.container)) as client:
            # First create base backup image
            old_format, features = self._get_rbd_support()
            LOG.debug("Creating backup base image='%(name)s' for volume "
                      "%(volume)s.",
                      {'name': backup_name, 'volume': volume_id})
            eventlet.tpool.Proxy(self.rbd.RBD()).create(
                ioctx=client.ioctx,
                name=backup_name,
                size=length,
                old_format=old_format,
                features=features,
                stripe_unit=self.rbd_stripe_unit,
                stripe_count=self.rbd_stripe_count)

            LOG.debug("Copying data from volume %s.", volume_id)
            dest_rbd = eventlet.tpool.Proxy(self.rbd.Image(client.ioctx,
                                            backup_name))
            try:
                rbd_meta = linuxrbd.RBDImageMetadata(dest_rbd,
                                                     backup.container,
                                                     self._ceph_backup_user,
                                                     self._ceph_backup_conf)
                rbd_fd = linuxrbd.RBDVolumeIOWrapper(rbd_meta)
                self._transfer_data(src_volume, src_name,
                                    eventlet.tpool.Proxy(rbd_fd),
                                    backup_name, length)
            finally:
                dest_rbd.close()

    @staticmethod
    def backup_snapshot_name_pattern():
        """Returns the pattern used to match backup snapshots.

        It is essential that snapshots created for purposes other than backups
        do not have this name format.
        """
        return r"^backup\.([a-z0-9\-]+?)\.snap\.(.+)$"

    @classmethod
    def get_backup_snaps(cls, rbd_image, sort=False):
        """Get all backup snapshots for the given rbd image.

        NOTE: this call is made public since these snapshots must be deleted
              before the base volume can be deleted.
        """
        snaps = rbd_image.list_snaps()

        backup_snaps = []
        for snap in snaps:
            search_key = cls.backup_snapshot_name_pattern()
            result = re.search(search_key, snap['name'])
            if result:
                backup_snaps.append({'name': result.group(0),
                                     'backup_id': result.group(1),
                                     'timestamp': result.group(2)})

        if sort:
            # Sort into ascending order of timestamp
            backup_snaps.sort(key=lambda x: x['timestamp'], reverse=True)

        return backup_snaps

    def _get_new_snap_name(self, backup_id):
        return utils.convert_str("backup.%s.snap.%s"
                                 % (backup_id, time.time()))

    def _get_backup_snap_name(self, rbd_image, name, backup_id):
        """Return the name of the snapshot associated with backup_id.

        The rbd image provided must be the base image used for an incremental
        backup.

        A backup is only allowed ONE associated snapshot. If more are found,
        exception.BackupOperationError is raised.
        """
        snaps = self.get_backup_snaps(rbd_image)

        LOG.debug("Looking for snapshot of backup base '%s'", name)

        if not snaps:
            LOG.debug("Backup base '%s' has no snapshots", name)
            return None

        snaps = [snap['name'] for snap in snaps
                 if snap['backup_id'] == backup_id]

        if not snaps:
            LOG.debug("Backup '%s' has no snapshot", backup_id)
            return None

        if len(snaps) > 1:
            msg = (_("Backup should only have one snapshot but instead has %s")
                   % len(snaps))
            LOG.error(msg)
            raise exception.BackupOperationError(msg)

        LOG.debug("Found snapshot '%s'", snaps[0])
        return snaps[0]

    def _get_volume_size_bytes(self, volume):
        """Return the size in bytes of the given volume.

        Raises exception.InvalidParameterValue if volume size is 0.
        """
        if int(volume['size']) == 0:
            errmsg = _("Need non-zero volume size")
            raise exception.InvalidParameterValue(errmsg)

        return int(volume['size']) * units.Gi

    def _backup_metadata(self, backup):
        """Backup volume metadata.

        NOTE(dosaboy): the metadata we are backing up is obtained from a
                       versioned api so we should not alter it in any way here.
                       We must also be sure that the service that will perform
                       the restore is compatible with version used.
        """
        json_meta = self.get_metadata(backup.volume_id)
        if not json_meta:
            LOG.debug("No metadata to backup for volume %s.", backup.volume_id)
            return

        LOG.debug("Backing up metadata for volume %s.", backup.volume_id)
        try:
            with eventlet.tpool.Proxy(rbd_driver.RADOSClient(self,
                                      backup.container)) as client:
                vol_meta_backup = VolumeMetadataBackup(client, backup.id)
                vol_meta_backup.set(json_meta)
        except exception.VolumeMetadataBackupExists as e:
            msg = (_("Failed to backup volume metadata - %s") % e)
            raise exception.BackupOperationError(msg)

    def backup(self, backup, volume_file, backup_metadata=True):
        """Backup volume and metadata (if available) to Ceph object store.

        If the source volume is an RBD we will attempt to do an
        incremental/differential backup, otherwise a full copy is performed.
        If this fails we will attempt to fall back to full copy.
        """
        volume = self.db.volume_get(self.context, backup.volume_id)
        updates = {}
        if not backup.container:
            backup.container = self._ceph_backup_pool
            backup.save()

        LOG.debug("Starting backup of volume='%s'.", volume.id)

        # Ensure we are at the beginning of the volume
        volume_file.seek(0)
        length = self._get_volume_size_bytes(volume)

        if backup.snapshot_id:
            do_full_backup = True
        elif self._file_is_rbd(volume_file):
            # If volume an RBD, attempt incremental or full backup.
            do_full_backup = False
            LOG.debug("Volume file is RBD: attempting optimized backup")
            try:
                updates = self._backup_rbd(backup, volume_file, volume.name,
                                           length)
            except exception.BackupRBDOperationFailed:
                with excutils.save_and_reraise_exception():
                    self.delete_backup(backup)
        else:
            if backup.parent_id:
                LOG.debug("Volume file is NOT RBD: can't perform "
                          "incremental backup.")
                raise exception.BackupRBDOperationFailed
            LOG.debug("Volume file is NOT RBD: will do full backup.")
            do_full_backup = True

        if do_full_backup:
            try:
                self._full_backup(backup, volume_file, volume.name, length)
            except exception.BackupOperationError:
                with excutils.save_and_reraise_exception():
                    self.delete_backup(backup)

        if backup_metadata:
            try:
                self._backup_metadata(backup)
            except exception.BackupOperationError:
                with excutils.save_and_reraise_exception():
                    # Cleanup.
                    self.delete_backup(backup)

        LOG.debug("Backup '%(backup_id)s' of volume %(volume_id)s finished.",
                  {'backup_id': backup.id, 'volume_id': volume.id})

        return updates

    def _full_restore(self, backup, dest_file, dest_name, length,
                      src_snap=None):
        """Restore volume using full copy i.e. all extents.

        This will result in all extents being copied from source to
        destination.
        """
        with eventlet.tpool.Proxy(rbd_driver.RADOSClient(self,
                                  backup.container)) as client:
            # If a source snapshot is provided we assume the base is diff
            # format.
            if src_snap:
                backup_name = self._get_backup_base_name(backup.volume_id,
                                                         backup=backup)
            else:
                backup_name = self._get_backup_base_name(backup.volume_id)

            # Retrieve backup volume
            src_rbd = eventlet.tpool.Proxy(self.rbd.Image(client.ioctx,
                                                          backup_name,
                                                          snapshot=src_snap,
                                                          read_only=True))
            try:
                rbd_meta = linuxrbd.RBDImageMetadata(src_rbd,
                                                     backup.container,
                                                     self._ceph_backup_user,
                                                     self._ceph_backup_conf)
                rbd_fd = linuxrbd.RBDVolumeIOWrapper(rbd_meta)
                self._transfer_data(eventlet.tpool.Proxy(rbd_fd), backup_name,
                                    dest_file, dest_name, length)
            finally:
                src_rbd.close()

    def _check_restore_vol_size(self, backup, restore_vol, restore_length,
                                src_pool):
        """Ensure that the restore volume is the correct size.

        If the restore volume was bigger than the backup, the diff restore will
        shrink it to the size of the original backup so we need to
        post-process and resize it back to its expected size.
        """
        backup_base = self._get_backup_base_name(backup.volume_id,
                                                 backup=backup)

        with eventlet.tpool.Proxy(rbd_driver.RADOSClient(self,
                                  backup.container)) as client:
            adjust_size = 0
            base_image = eventlet.tpool.Proxy(self.rbd.Image(client.ioctx,
                                              utils.convert_str(backup_base),
                                              read_only=True))
            try:
                if restore_length != base_image.size():
                    adjust_size = restore_length
            finally:
                base_image.close()

        if adjust_size:
            LOG.debug("Adjusting restore vol size")
            restore_vol.rbd_image.resize(adjust_size)

    def _diff_restore_rbd(self, backup, restore_file, restore_name,
                          restore_point, restore_length):
        """Attempt restore rbd volume from backup using diff transfer."""
        rbd_user = restore_file.rbd_user
        rbd_pool = restore_file.rbd_pool
        rbd_conf = restore_file.rbd_conf
        base_name = self._get_backup_base_name(backup.volume_id,
                                               backup=backup)

        LOG.debug("Attempting incremental restore from base='%(base)s' "
                  "snap='%(snap)s'",
                  {'base': base_name, 'snap': restore_point})
        before = time.time()
        try:
            self._rbd_diff_transfer(base_name, backup.container,
                                    restore_name, rbd_pool,
                                    src_user=self._ceph_backup_user,
                                    src_conf=self._ceph_backup_conf,
                                    dest_user=rbd_user, dest_conf=rbd_conf,
                                    src_snap=restore_point)
        except exception.BackupRBDOperationFailed:
            LOG.exception("Differential restore failed, trying full restore")
            raise

        # If the volume we are restoring to is larger than the backup volume,
        # we will need to resize it after the diff import since import-diff
        # appears to shrink the target rbd volume to the size of the original
        # backup volume.
        self._check_restore_vol_size(backup, restore_file, restore_length,
                                     rbd_pool)

        LOG.debug("Restore transfer completed in %.4fs",
                  (time.time() - before))

    def _get_restore_point(self, base_name, backup_id):
        """Get restore point snapshot name for incremental backup.

        If the backup was not incremental (determined by the fact that the
        base has no snapshots/restore points), None is returned. Otherwise, the
        restore point associated with backup_id is returned.
        """
        with eventlet.tpool.Proxy(rbd_driver.RADOSClient(self,
                                  self._ceph_backup_pool)) as client:
            base_rbd = eventlet.tpool.Proxy(self.rbd.Image(client.ioctx,
                                            base_name, read_only=True))
            try:
                restore_point = self._get_backup_snap_name(base_rbd, base_name,
                                                           backup_id)
            finally:
                base_rbd.close()

        return restore_point

    def _rbd_has_extents(self, rbd_volume):
        """Check whether the given rbd volume has extents.

        Return True if has extents, otherwise False.
        """
        extents = []

        def iter_cb(offset, length, exists):
            if exists:
                extents.append(length)

        rbd_volume.diff_iterate(0, rbd_volume.size(), None, iter_cb)

        if extents:
            LOG.debug("RBD has %s extents", sum(extents))
            return True

        return False

    def _diff_restore_allowed(self, base_name, backup, volume, volume_file,
                              rados_client):
        """Determine if differential restore is possible and restore point.

        Determine whether a differential restore is possible/allowed,
        and find out the restore point if backup base is diff-format.

        In order for a differential restore to be performed we need:
            * destination volume must be RBD
            * destination volume must have zero extents
            * backup base image must exist
            * backup must have a restore point
            * target volume is different from source volume of backup

        Returns True if differential restore is allowed, False otherwise.
        Return the restore point if back base is diff-format.
        """
        # NOTE(dosaboy): base_name here must be diff format.
        rbd_exists, base_name = self._rbd_image_exists(base_name,
                                                       backup.volume_id,
                                                       rados_client)

        if not rbd_exists:
            return False, None

        # Get the restore point. If no restore point is found, we assume
        # that the backup was not performed using diff/incremental methods
        # so we enforce full copy.
        restore_point = self._get_restore_point(base_name, backup.id)

        if restore_point:
            if self._file_is_rbd(volume_file):
                LOG.debug("Volume file is RBD.")
                # If the volume we are restoring to is the volume the backup
                # was made from, force a full restore since a diff will not
                # work in this case.
                if volume.id == backup.volume_id:
                    LOG.debug("Destination volume is same as backup source "
                              "volume %s - forcing full copy.", volume.id)
                    return False, restore_point

                # If the destination volume has extents we cannot allow a diff
                # restore.
                if self._rbd_has_extents(volume_file.rbd_image):
                    # We return the restore point so that a full copy is done
                    # from snapshot.
                    LOG.debug("Destination has extents - forcing full copy")
                    return False, restore_point

                return True, restore_point
            else:
                LOG.debug("Volume file is NOT RBD.")
        else:
            LOG.info("No restore point found for backup='%(backup)s' of "
                     "volume %(volume)s although base image is found - "
                     "forcing full copy.",
                     {'backup': backup.id,
                      'volume': backup.volume_id})
        return False, restore_point

    def _restore_volume(self, backup, volume, volume_file):
        """Restore volume from backup using diff transfer if possible.

        Attempts a differential restore and reverts to full copy if diff fails.
        """
        length = int(volume.size) * units.Gi

        if backup.service_metadata:
            base_name = self._get_backup_base_name(backup.volume_id, backup)
        else:
            base_name = self._get_backup_base_name(backup.volume_id)

        with eventlet.tpool.Proxy(rbd_driver.RADOSClient(
                                  self, backup.container)) as client:
            diff_allowed, restore_point = \
                self._diff_restore_allowed(base_name, backup, volume,
                                           volume_file, client)

        do_full_restore = True
        if diff_allowed:
            # Attempt diff
            try:
                LOG.debug("Attempting differential restore.")
                self._diff_restore_rbd(backup, volume_file, volume.name,
                                       restore_point, length)
                do_full_restore = False
            except exception.BackupRBDOperationFailed:
                LOG.debug("Forcing full restore to volume %s.",
                          volume.id)

        if do_full_restore:
            # Otherwise full copy
            LOG.debug("Running full restore.")
            self._full_restore(backup, volume_file, volume.name,
                               length, src_snap=restore_point)

    def _restore_metadata(self, backup, volume_id):
        """Restore volume metadata from backup.

        If this backup has associated metadata, save it to the restore target
        otherwise do nothing.
        """
        try:
            with eventlet.tpool.Proxy(rbd_driver.RADOSClient(self)) as client:
                meta_bak = VolumeMetadataBackup(client, backup.id)
                meta = meta_bak.get()
                if meta is not None:
                    self.put_metadata(volume_id, meta)
                else:
                    LOG.debug("Volume %s has no backed up metadata.",
                              backup.volume_id)
        except exception.BackupMetadataUnsupportedVersion:
            msg = _("Metadata restore failed due to incompatible version")
            LOG.error(msg)
            raise exception.BackupOperationError(msg)

    def restore(self, backup, volume_id, volume_file):
        """Restore volume from backup in Ceph object store.

        If volume metadata is available this will also be restored.
        """
        target_volume = self.db.volume_get(self.context, volume_id)
        LOG.debug('Starting restore from Ceph backup=%(src)s to '
                  'volume=%(dest)s',
                  {'src': backup.id, 'dest': target_volume.name})

        try:
            self._restore_volume(backup, target_volume, volume_file)

            # Be tolerant of IO implementations that do not support fileno()
            try:
                fileno = volume_file.fileno()
            except IOError:
                LOG.debug("Restore target I/O object does not support "
                          "fileno() - skipping call to fsync().")
            else:
                os.fsync(fileno)

            self._restore_metadata(backup, volume_id)

            LOG.debug('Restore to volume %s finished successfully.',
                      volume_id)
        except exception.BackupOperationError as e:
            LOG.error('Restore to volume %(volume)s finished with error - '
                      '%(error)s.', {'error': e, 'volume': volume_id})
            raise

    def delete_backup(self, backup):
        """Delete the given backup from Ceph object store."""
        LOG.debug('Delete started for backup=%s', backup.id)

        delete_failed = False
        has_pool = True
        try:
            self._try_delete_base_image(backup)
        except self.rbd.ImageNotFound:
            LOG.warning(
                "RBD image for backup %(backup)s of volume %(volume)s "
                "not found. Deleting backup metadata.",
                {'backup': backup.id, 'volume': backup.volume_id})
            delete_failed = True
        except self.rados.ObjectNotFound:
            LOG.warning("The pool %(pool)s doesn't exist.",
                        {'pool': backup.container})
            delete_failed = True
            has_pool = False

        if has_pool:
            with eventlet.tpool.Proxy(rbd_driver.RADOSClient(
                                      self, backup.container)) as client:
                VolumeMetadataBackup(client, backup.id).remove_if_exists()

        if delete_failed:
            LOG.info("Delete of backup '%(backup)s' for volume '%(volume)s' "
                     "finished with warning.",
                     {'backup': backup.id, 'volume': backup.volume_id})
        else:
            LOG.debug("Delete of backup '%(backup)s' for volume "
                      "'%(volume)s' finished.",
                      {'backup': backup.id, 'volume': backup.volume_id})
