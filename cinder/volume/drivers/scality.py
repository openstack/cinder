# Copyright (c) 2013 Scality
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

"""
Scality SOFS Volume Driver.
"""


import errno
import os
import urllib2
import urlparse

from oslo.config import cfg

from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import log as logging
from cinder.volume import driver


LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('scality_sofs_config',
               default=None,
               help='Path or URL to Scality SOFS configuration file'),
    cfg.StrOpt('scality_sofs_mount_point',
               default='$state_path/scality',
               help='Base dir where Scality SOFS shall be mounted'),
    cfg.StrOpt('scality_sofs_volume_dir',
               default='cinder/volumes',
               help='Path from Scality SOFS root to volume dir'),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)


class ScalityDriver(driver.VolumeDriver):
    """Scality SOFS cinder driver.

    Creates sparse files on SOFS for hypervisors to use as block
    devices.
    """

    def _check_prerequisites(self):
        """Sanity checks before attempting to mount SOFS."""

        # config is mandatory
        config = CONF.scality_sofs_config
        if not config:
            msg = _("Value required for 'scality_sofs_config'")
            LOG.warn(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # config can be a file path or a URL, check it
        if urlparse.urlparse(config).scheme == '':
            # turn local path into URL
            config = 'file://%s' % config
        try:
            urllib2.urlopen(config, timeout=5).close()
        except urllib2.URLError as e:
            msg = _("Cannot access 'scality_sofs_config': %s") % e
            LOG.warn(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # mount.sofs must be installed
        if not os.access('/sbin/mount.sofs', os.X_OK):
            msg = _("Cannot execute /sbin/mount.sofs")
            LOG.warn(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _makedirs(self, path):
        try:
            os.makedirs(path)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise

    def _mount_sofs(self):
        config = CONF.scality_sofs_config
        mount_path = CONF.scality_sofs_mount_point
        sysdir = os.path.join(mount_path, 'sys')

        self._makedirs(mount_path)
        if not os.path.isdir(sysdir):
            self._execute('mount', '-t', 'sofs', config, mount_path,
                          run_as_root=True)
        if not os.path.isdir(sysdir):
            msg = _("Cannot mount Scality SOFS, check syslog for errors")
            LOG.warn(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _size_bytes(self, size_in_g):
        if int(size_in_g) == 0:
            return 100 * 1024 * 1024
        return int(size_in_g) * 1024 * 1024 * 1024

    def _create_file(self, path, size):
        with open(path, "ab") as f:
            f.truncate(size)
        os.chmod(path, 0o666)

    def _copy_file(self, src_path, dest_path):
        self._execute('dd', 'if=%s' % src_path, 'of=%s' % dest_path,
                      'bs=1M', 'conv=fsync,nocreat,notrunc',
                      run_as_root=True)

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        self._check_prerequisites()
        self._mount_sofs()
        voldir = os.path.join(CONF.scality_sofs_mount_point,
                              CONF.scality_sofs_volume_dir)
        if not os.path.isdir(voldir):
            self._makedirs(voldir)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        self._check_prerequisites()
        voldir = os.path.join(CONF.scality_sofs_mount_point,
                              CONF.scality_sofs_volume_dir)
        if not os.path.isdir(voldir):
            msg = _("Cannot find volume dir for Scality SOFS at '%s'") % voldir
            LOG.warn(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def create_volume(self, volume):
        """Creates a logical volume.

        Can optionally return a Dictionary of changes to the volume
        object to be persisted.
        """
        self._create_file(self.local_path(volume),
                          self._size_bytes(volume['size']))
        volume['provider_location'] = self._sofs_path(volume)
        return {'provider_location': volume['provider_location']}

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        changes = self.create_volume(volume)
        self._copy_file(self.local_path(snapshot),
                        self.local_path(volume))
        return changes

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        os.remove(self.local_path(volume))

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        volume_path = os.path.join(CONF.scality_sofs_mount_point,
                                   CONF.scality_sofs_volume_dir,
                                   snapshot['volume_name'])
        snapshot_path = self.local_path(snapshot)
        self._create_file(snapshot_path,
                          self._size_bytes(snapshot['volume_size']))
        self._copy_file(volume_path, snapshot_path)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        os.remove(self.local_path(snapshot))

    def _sofs_path(self, volume):
        return os.path.join(CONF.scality_sofs_volume_dir,
                            volume['name'])

    def local_path(self, volume):
        return os.path.join(CONF.scality_sofs_mount_point,
                            self._sofs_path(volume))

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        pass

    def create_export(self, context, volume):
        """Exports the volume.

        Can optionally return a Dictionary of changes to the volume
        object to be persisted.
        """
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        return {
            'driver_volume_type': 'scality',
            'data': {
                'sofs_path': self._sofs_path(volume),
            }
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        pass

    def detach_volume(self, context, volume_id):
        """Callback for volume detached."""
        pass

    def get_volume_stats(self, refresh=False):
        """Return the current state of the volume service.

        If 'refresh' is True, run the update first.
        """
        stats = {
            'vendor_name': 'Scality',
            'driver_version': '1.0',
            'storage_protocol': 'scality',
            'total_capacity_gb': 'infinite',
            'free_capacity_gb': 'infinite',
            'reserved_percentage': 0,
        }
        backend_name = self.configuration.safe_get('volume_backend_name')
        stats['volume_backend_name'] = backend_name or 'Scality_SOFS'
        return stats

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        image_utils.fetch_to_raw(context,
                                 image_service,
                                 image_id,
                                 self.local_path(volume))
        self.create_volume(volume)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        image_utils.upload_volume(context,
                                  image_service,
                                  image_meta,
                                  self.local_path(volume))

    def clone_image(self, volume, image_location):
        """Create a volume efficiently from an existing image.

        image_location is a string whose format depends on the
        image service backend in use. The driver should use it
        to determine whether cloning is possible.

        Returns a boolean indicating whether cloning occurred
        """
        return False
