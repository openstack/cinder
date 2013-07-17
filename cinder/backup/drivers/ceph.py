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

"""Ceph Backup Service Implementation"""

import os
import time

import eventlet
from oslo.config import cfg

from cinder.backup.driver import BackupDriver
from cinder import exception
from cinder.openstack.common import log as logging
from cinder import units
import cinder.volume.drivers.rbd as rbddriver

try:
    import rados
    import rbd
except ImportError:
    rados = None
    rbd = None

LOG = logging.getLogger(__name__)

service_opts = [
    cfg.StrOpt('backup_ceph_conf', default='/etc/ceph/ceph.conf',
               help='Ceph config file to use.'),
    cfg.StrOpt('backup_ceph_user', default='cinder',
               help='the Ceph user to connect with'),
    cfg.StrOpt('backup_ceph_chunk_size', default=(units.MiB * 128),
               help='the chunk size in bytes that a backup will be broken '
                    'into before transfer to backup store'),
    cfg.StrOpt('backup_ceph_pool', default='backups',
               help='the Ceph pool to backup to'),
    cfg.StrOpt('backup_ceph_stripe_unit', default=0,
               help='RBD stripe unit to use when creating a backup image'),
    cfg.StrOpt('backup_ceph_stripe_count', default=0,
               help='RBD stripe count to use when creating a backup image')
]

CONF = cfg.CONF
CONF.register_opts(service_opts)


class CephBackupDriver(BackupDriver):
    """Backup up Cinder volumes to Ceph Object Store"""

    def __init__(self, context, db_driver=None):
        super(CephBackupDriver, self).__init__(db_driver)
        self.rbd = rbd
        self.rados = rados
        self.context = context
        self.chunk_size = CONF.backup_ceph_chunk_size
        if self._supports_stripingv2():
            self.rbd_stripe_unit = int(CONF.backup_ceph_stripe_unit)
            self.rbd_stripe_count = int(CONF.backup_ceph_stripe_count)
        else:
            LOG.info("rbd striping not supported - ignoring conf settings "
                     "for rbd striping")
            self.rbd_stripe_count = 0
            self.rbd_stripe_unit = 0

        self._ceph_user = str(CONF.backup_ceph_user)
        self._ceph_pool = str(CONF.backup_ceph_pool)
        self._ceph_conf = str(CONF.backup_ceph_conf)

    def _supports_layering(self):
        """
        Determine whether copy-on-write is supported by our version of librbd
        """
        return hasattr(self.rbd, 'RBD_FEATURE_LAYERING')

    def _supports_stripingv2(self):
        """
        Determine whether striping is supported by our version of librbd
        """
        return hasattr(self.rbd, 'RBD_FEATURE_STRIPINGV2')

    def _get_rbd_support(self):
        old_format = True
        features = 0
        if self._supports_layering():
            old_format = False
            features |= self.rbd.RBD_FEATURE_LAYERING
        if self._supports_stripingv2():
            old_format = False
            features |= self.rbd.RBD_FEATURE_STRIPINGV2

        return (old_format, features)

    def _connect_to_rados(self, pool=None):
        """Establish connection to the Ceph cluster"""
        client = self.rados.Rados(rados_id=self._ceph_user,
                                  conffile=self._ceph_conf)
        try:
            client.connect()
            pool_to_open = str(pool or self._ceph_pool)
            ioctx = client.open_ioctx(pool_to_open)
            return client, ioctx
        except self.rados.Error:
            # shutdown cannot raise an exception
            client.shutdown()
            raise

    def _disconnect_from_rados(self, client, ioctx):
        """Terminate connection with the Ceph cluster"""
        # closing an ioctx cannot raise an exception
        ioctx.close()
        client.shutdown()

    def _get_backup_base_name(self, volume_id, backup_id):
        """Return name of base image used for backup."""
        # Ensure no unicode
        return str("volume-%s.backup.%s" % (volume_id, backup_id))

    def _transfer_data(self, src, dest, dest_name, length, dest_is_rbd=False):
        """
        Transfer data between file and rbd. If destination is rbd, source is
        assumed to be file, otherwise source is assumed to be rbd.
        """
        chunks = int(length / self.chunk_size)
        LOG.debug("transferring %s chunks of %s bytes to '%s'" %
                  (chunks, self.chunk_size, dest_name))
        for chunk in xrange(0, chunks):
            offset = chunk * self.chunk_size
            before = time.time()

            if dest_is_rbd:
                dest.write(src.read(self.chunk_size), offset)
                # note(dosaboy): librbd writes are synchronous so flush() will
                # have not effect. Also, flush only supported in more recent
                # versions of librbd.
            else:
                dest.write(src.read(offset, self.chunk_size))
                dest.flush()

            delta = (time.time() - before)
            rate = (self.chunk_size / delta) / 1024
            LOG.debug("transferred chunk %s of %s (%dK/s)" %
                      (chunk, chunks, rate))

            # yield to any other pending backups
            eventlet.sleep(0)

        rem = int(length % self.chunk_size)
        if rem:
            LOG.debug("transferring remaining %s bytes" % (rem))
            offset = (length - rem)
            if dest_is_rbd:
                dest.write(src.read(rem), offset)
                # note(dosaboy): librbd writes are synchronous so flush() will
                # have not effect. Also, flush only supported in more recent
                # versions of librbd.
            else:
                dest.write(src.read(offset, rem))
                dest.flush()

            # yield to any other pending backups
            eventlet.sleep(0)

    def _backup_volume_from_file(self, backup_name, backup_size, volume_file):
        """Backup a volume from file stream"""
        LOG.debug("performing backup from file")

        old_format, features = self._get_rbd_support()

        with rbddriver.RADOSClient(self, self._ceph_pool) as client:
            self.rbd.RBD().create(ioctx=client.ioctx,
                                  name=backup_name,
                                  size=backup_size,
                                  old_format=old_format,
                                  features=features,
                                  stripe_unit=self.rbd_stripe_unit,
                                  stripe_count=self.rbd_stripe_count)

            dest_rbd = self.rbd.Image(client.ioctx, backup_name)
            try:
                self._transfer_data(volume_file, dest_rbd, backup_name,
                                    backup_size, dest_is_rbd=True)
            finally:
                dest_rbd.close()

    def backup(self, backup, volume_file):
        """Backup the given volume to Ceph object store"""
        backup_id = backup['id']
        volume = self.db.volume_get(self.context, backup['volume_id'])
        backup_name = self._get_backup_base_name(volume['id'], backup_id)

        LOG.debug("Starting backup of volume='%s' to rbd='%s'" %
                  (volume['name'], backup_name))

        if int(volume['size']) == 0:
            raise exception.InvalidParameterValue("need non-zero volume size")
        else:
            backup_size = int(volume['size']) * units.GiB

        if volume_file:
            self._backup_volume_from_file(backup_name, backup_size,
                                          volume_file)
        else:
            errmsg = ("No volume_file was provided so I cannot do requested "
                      "backup (id=%s)" % (backup_id))
            raise exception.BackupVolumeInvalidType(errmsg)

        self.db.backup_update(self.context, backup['id'],
                              {'container': self._ceph_pool})

        LOG.debug(_("backup '%s' finished.") % (backup_id))

    def restore(self, backup, volume_id, volume_file):
        """Restore the given volume backup from Ceph object store"""
        volume = self.db.volume_get(self.context, volume_id)
        backup_name = self._get_backup_base_name(backup['volume_id'],
                                                 backup['id'])

        LOG.debug('starting backup restore from Ceph backup=%s '
                  'to volume=%s' % (backup['id'], volume['name']))

        # Ensure we are at the beginning of the volume
        volume_file.seek(0)

        backup_size = int(volume['size']) * units.GiB

        with rbddriver.RADOSClient(self, self._ceph_pool) as client:
            src_rbd = self.rbd.Image(client.ioctx, backup_name)
            try:
                self._transfer_data(src_rbd, volume_file, volume['name'],
                                    backup_size)
            finally:
                src_rbd.close()

        # Be tolerant to IO implementations that do not support fileno()
        try:
            fileno = volume_file.fileno()
        except IOError:
            LOG.info("volume_file does not support fileno() so skipping "
                     "fsync()")
        else:
            os.fsync(fileno)

        LOG.debug('restore %s to %s finished.' % (backup['id'], volume_id))

    def delete(self, backup):
        """Delete the given backup from Ceph object store"""
        backup_id = backup['id']
        backup_name = self._get_backup_base_name(backup['volume_id'],
                                                 backup_id)

        LOG.debug('delete started for backup=%s', backup['id'])

        try:
            with rbddriver.RADOSClient(self) as client:
                self.rbd.RBD().remove(client.ioctx, backup_name)
        except self.rbd.ImageNotFound:
            LOG.warning("rbd image '%s' not found but continuing anyway so "
                        "that db entry can be removed" % (backup_name))

        LOG.debug(_("delete '%s' finished") % (backup_id))


def get_backup_driver(context):
    return CephBackupDriver(context)
