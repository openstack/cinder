#    Copyright 2012 OpenStack LLC
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
RADOS Block Device Driver
"""

import json
import os
import tempfile
import urllib

from oslo.config import cfg

from cinder import exception
from cinder import flags
from cinder.image import image_utils
from cinder.openstack.common import log as logging
from cinder import utils
from cinder.volume import driver

LOG = logging.getLogger(__name__)

rbd_opts = [
    cfg.StrOpt('rbd_pool',
               default='rbd',
               help='the RADOS pool in which rbd volumes are stored'),
    cfg.StrOpt('rbd_user',
               default=None,
               help='the RADOS client name for accessing rbd volumes'),
    cfg.StrOpt('rbd_secret_uuid',
               default=None,
               help='the libvirt uuid of the secret for the rbd_user'
                    'volumes'),
    cfg.StrOpt('volume_tmp_dir',
               default=None,
               help='where to store temporary image files if the volume '
                    'driver does not write them directly to the volume'), ]

FLAGS = flags.FLAGS
FLAGS.register_opts(rbd_opts)

VERSION = '1.0'


class RBDDriver(driver.VolumeDriver):
    """Implements RADOS block device (RBD) volume commands"""
    def __init__(self, *args, **kwargs):
        super(RBDDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(rbd_opts)
        self._stats = dict(
            volume_backend_name='RBD',
            vendor_name='Open Source',
            driver_version=VERSION,
            storage_protocol='ceph',
            total_capacity_gb='unknown',
            free_capacity_gb='unknown',
            reserved_percentage=0)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met"""
        (stdout, stderr) = self._execute('rados', 'lspools')
        pools = stdout.split("\n")
        if self.configuration.rbd_pool not in pools:
            exception_message = (_("rbd has no pool %s") %
                                 self.configuration.rbd_pool)
            raise exception.VolumeBackendAPIException(data=exception_message)

    def _update_volume_stats(self):
        stats = dict(
            total_capacity_gb='unknown',
            free_capacity_gb='unknown')
        try:
            stdout, _err = self._execute('rados', 'df', '--format', 'json')
            new_stats = json.loads(stdout)
            total = int(new_stats['total_space']) / 1024 ** 2
            free = int(new_stats['total_avail']) / 1024 ** 2
            stats['total_capacity_gb'] = total
            stats['free_capacity_gb'] = free
        except exception.ProcessExecutionError:
            # just log and return unknown capacities
            LOG.exception(_('error refreshing volume stats'))
        self._stats.update(stats)

    def get_volume_stats(self, refresh=False):
        """Return the current state of the volume service. If 'refresh' is
           True, run the update first."""
        if refresh:
            self._update_volume_stats()
        return self._stats

    def _supports_layering(self):
        stdout, _ = self._execute('rbd', '--help')
        return 'clone' in stdout

    def create_cloned_volume(self, volume, src_vref):
        raise NotImplementedError()

    def create_volume(self, volume):
        """Creates a logical volume."""
        if int(volume['size']) == 0:
            size = 100
        else:
            size = int(volume['size']) * 1024
        args = ['rbd', 'create',
                '--pool', self.configuration.rbd_pool,
                '--size', size,
                volume['name']]
        if self._supports_layering():
            args += ['--new-format']
        self._try_execute(*args)

    def _clone(self, volume, src_pool, src_image, src_snap):
        self._try_execute('rbd', 'clone',
                          '--pool', src_pool,
                          '--image', src_image,
                          '--snap', src_snap,
                          '--dest-pool', self.configuration.rbd_pool,
                          '--dest', volume['name'])

    def _resize(self, volume):
        size = int(volume['size']) * 1024
        self._try_execute('rbd', 'resize',
                          '--pool', self.configuration.rbd_pool,
                          '--image', volume['name'],
                          '--size', size)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self._clone(volume, self.configuration.rbd_pool,
                    snapshot['volume_name'], snapshot['name'])
        if int(volume['size']):
            self._resize(volume)

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        stdout, _ = self._execute('rbd', 'snap', 'ls',
                                  '--pool', self.configuration.rbd_pool,
                                  volume['name'])
        if stdout.count('\n') > 1:
            raise exception.VolumeIsBusy(volume_name=volume['name'])
        self._try_execute('rbd', 'rm',
                          '--pool', self.configuration.rbd_pool,
                          volume['name'])

    def create_snapshot(self, snapshot):
        """Creates an rbd snapshot"""
        self._try_execute('rbd', 'snap', 'create',
                          '--pool', self.configuration.rbd_pool,
                          '--snap', snapshot['name'],
                          snapshot['volume_name'])
        if self._supports_layering():
            self._try_execute('rbd', 'snap', 'protect',
                              '--pool', self.configuration.rbd_pool,
                              '--snap', snapshot['name'],
                              snapshot['volume_name'])

    def delete_snapshot(self, snapshot):
        """Deletes an rbd snapshot"""
        if self._supports_layering():
            try:
                self._try_execute('rbd', 'snap', 'unprotect',
                                  '--pool', self.configuration.rbd_pool,
                                  '--snap', snapshot['name'],
                                  snapshot['volume_name'])
            except exception.ProcessExecutionError:
                raise exception.SnapshotIsBusy(snapshot_name=snapshot['name'])
        self._try_execute('rbd', 'snap', 'rm',
                          '--pool', self.configuration.rbd_pool,
                          '--snap', snapshot['name'],
                          snapshot['volume_name'])

    def local_path(self, volume):
        """Returns the path of the rbd volume."""
        # This is the same as the remote path
        # since qemu accesses it directly.
        return "rbd:%s/%s" % (self.configuration.rbd_pool, volume['name'])

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        pass

    def create_export(self, context, volume):
        """Exports the volume"""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume"""
        pass

    def initialize_connection(self, volume, connector):
        return {
            'driver_volume_type': 'rbd',
            'data': {
                'name': '%s/%s' % (self.configuration.rbd_pool,
                                   volume['name']),
                'auth_enabled': (self.configuration.rbd_secret_uuid
                                 is not None),
                'auth_username': self.configuration.rbd_user,
                'secret_type': 'ceph',
                'secret_uuid': self.configuration.rbd_secret_uuid, }
        }

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
        stdout, _ = self._execute('ceph', 'fsid')
        return stdout.rstrip('\n')

    def _is_cloneable(self, image_location):
        try:
            fsid, pool, image, snapshot = self._parse_location(image_location)
        except exception.ImageUnacceptable:
            return False

        if self._get_fsid() != fsid:
            reason = _('%s is in a different ceph cluster') % image_location
            LOG.debug(reason)
            return False

        # check that we can read the image
        try:
            self._execute('rbd', 'info',
                          '--pool', pool,
                          '--image', image,
                          '--snap', snapshot)
        except exception.ProcessExecutionError:
            LOG.debug(_('Unable to read image %s') % image_location)
            return False

        return True

    def clone_image(self, volume, image_location):
        if image_location is None or not self._is_cloneable(image_location):
            return False
        _, pool, image, snapshot = self._parse_location(image_location)
        self._clone(volume, pool, image, snapshot)
        self._resize(volume)
        return True

    def _ensure_tmp_exists(self):
        tmp_dir = self.configuration.volume_tmp_dir
        if tmp_dir and not os.path.exists(tmp_dir):
            os.makedirs(tmp_dir)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        # TODO(jdurgin): replace with librbd
        # this is a temporary hack, since rewriting this driver
        # to use librbd would take too long
        self._ensure_tmp_exists()
        tmp_dir = self.configuration.volume_tmp_dir

        with tempfile.NamedTemporaryFile(dir=tmp_dir) as tmp:
            image_utils.fetch_to_raw(context, image_service, image_id,
                                     tmp.name)
            # import creates the image, so we must remove it first
            self._try_execute('rbd', 'rm',
                              '--pool', self.configuration.rbd_pool,
                              volume['name'])

            args = ['rbd', 'import',
                    '--pool', self.configuration.rbd_pool,
                    tmp.name, volume['name']]
            if self._supports_layering():
                args += ['--new-format']
            self._try_execute(*args)
        self._resize(volume)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        self._ensure_tmp_exists()

        tmp_dir = self.configuration.volume_tmp_dir or '/tmp'
        tmp_file = os.path.join(tmp_dir,
                                volume['name'] + '-' + image_meta['id'])
        with utils.remove_path_on_error(tmp_file):
            self._try_execute('rbd', 'export',
                              '--pool', self.configuration.rbd_pool,
                              volume['name'], tmp_file)
            image_utils.upload_volume(context, image_service,
                                      image_meta, tmp_file)
        os.unlink(tmp_file)
