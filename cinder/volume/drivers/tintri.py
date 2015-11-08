# Copyright (c) 2015 Tintri.  All rights reserved.
# Copyright (c) 2012 NetApp, Inc.  All rights reserved.
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
Volume driver for Tintri storage.
"""

import json
import math
import os
import re
import socket

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units
import requests
from six.moves import urllib

from cinder import exception
from cinder import utils
from cinder.i18n import _, _LE, _LI, _LW
from cinder.image import image_utils
from cinder.volume import driver
from cinder.volume.drivers import nfs

LOG = logging.getLogger(__name__)
default_api_version = 'v310'
img_prefix = 'image-'
tintri_path = '/tintri/'


tintri_opts = [
    cfg.StrOpt('tintri_server_hostname',
               help='The hostname (or IP address) for the storage system'),
    cfg.StrOpt('tintri_server_username',
               help='User name for the storage system'),
    cfg.StrOpt('tintri_server_password',
               help='Password for the storage system',
               secret=True),
    cfg.StrOpt('tintri_api_version',
               default=default_api_version,
               help='API version for the storage system'),
]

CONF = cfg.CONF
CONF.register_opts(tintri_opts)


class TintriDriver(driver.ManageableVD,
                   driver.CloneableImageVD,
                   driver.SnapshotVD,
                   nfs.NfsDriver):
    """Base class for Tintri driver."""

    VENDOR = 'Tintri'
    VERSION = '2.1.0.1'
    REQUIRED_OPTIONS = ['tintri_server_hostname', 'tintri_server_username',
                        'tintri_server_password']

    def __init__(self, *args, **kwargs):
        self._execute = None
        self._context = None
        super(TintriDriver, self).__init__(*args, **kwargs)
        self._execute_as_root = True
        self.configuration.append_config_values(tintri_opts)

    def do_setup(self, context):
        super(TintriDriver, self).do_setup(context)
        self._context = context
        self._check_ops(self.REQUIRED_OPTIONS, self.configuration)
        self._hostname = getattr(self.configuration, 'tintri_server_hostname')
        self._username = getattr(self.configuration, 'tintri_server_username',
                                 CONF.tintri_server_username)
        self._password = getattr(self.configuration, 'tintri_server_password')
        self._api_version = getattr(self.configuration, 'tintri_api_version',
                                    CONF.tintri_api_version)

    def get_pool(self, volume):
        """Returns pool name where volume resides.

        :param volume: The volume hosted by the driver.
        :return: Name of the pool where given volume is hosted.
        """
        return volume['provider_location']

    def _get_client(self):
        """Returns a Tintri REST client connection."""
        return TClient(self._hostname, self._username, self._password,
                       self._api_version)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        (__, path) = self._get_export_ip_path(snapshot.volume_id)
        volume_path = '%s/%s' % (path, snapshot.volume_name)
        volume_path = '%(path)s/%(volume_name)s' % {
            'path': path,
            'volume_name': snapshot.volume_name,
        }
        model_update = {}
        with self._get_client() as c:
            provider_id = c.create_snapshot(volume_path,
                                            snapshot.volume.display_name or
                                            snapshot.volume_name,
                                            snapshot.volume_id,
                                            snapshot.display_name or
                                            snapshot.name)
            snapshot.provider_id = provider_id
            # Store Tintri snapshot ID as snapshot provider_id
            model_update['provider_id'] = provider_id

        return model_update

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        if snapshot.provider_id:
            with self._get_client() as c:
                c.delete_snapshot(snapshot.provider_id)
        else:
            LOG.info(_LI('Snapshot %s not found'), snapshot.name)

    def _check_ops(self, required_ops, configuration):
        """Ensures that the options we care about are set."""
        for op in required_ops:
            if not getattr(configuration, op):
                LOG.error(_LE('Configuration value %s is not set.'), op)
                raise exception.InvalidConfigurationValue(option=op,
                                                          value=None)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from snapshot."""
        vol_size = volume.size
        snap_size = snapshot.volume_size

        self._clone_snapshot(snapshot.provider_id, volume.name,
                             snapshot.volume_id)
        share = self._get_provider_location(snapshot.volume_id)
        volume['provider_location'] = share
        path = self.local_path(volume)

        self._set_rw_permissions(path)
        if vol_size != snap_size:
            try:
                self.extend_volume(volume, vol_size)
            except Exception:
                LOG.error(_LE('Resizing %s failed. Cleaning volume.'),
                          volume.name)
                self._delete_file(path)
                raise

        return {'provider_location': volume['provider_location']}

    def _clone_snapshot(self, snapshot_id, clone_name, volume_id, share=None):
        """Clones volume from snapshot."""
        (host, path) = self._get_export_ip_path(volume_id, share)
        clone_path = '%s/%s-d' % (path, clone_name)
        with self._get_client() as c:
            c.clone_volume(snapshot_id, clone_path)

        self._move_cloned_volume(clone_name, volume_id, share)

    def _move_cloned_volume(self, clone_name, volume_id, share=None):
        local_path = self._get_local_path(volume_id, share)
        source_path = os.path.join(local_path, clone_name + '-d')
        if self._is_volume_present(source_path):
            source_file = os.listdir(source_path)[0]
            source = os.path.join(source_path, source_file)
            target = os.path.join(local_path, clone_name)
            moved = self._move_file(source, target)
            self._execute('rm', '-rf', source_path,
                          run_as_root=self._execute_as_root)
            if not moved:
                msg = (_('Failed to move volume %s.') % source)
                raise exception.VolumeDriverException(msg)
        else:
            raise exception.VolumeDriverException(
                _('Volume %s not found.') % source_path)

    def _clone_volume_to_volume(self, volume_name, clone_name,
                                volume_display_name, volume_id,
                                share=None, image_id=None):
        """Creates volume snapshot then clones volume."""
        (host, path) = self._get_export_ip_path(volume_id, share)
        volume_path = '%s/%s' % (path, volume_name)
        clone_path = '%s/%s-d' % (path, clone_name)
        with self._get_client() as c:
            if share and image_id:
                snapshot_id = self._create_image_snapshot(volume_name, share,
                                                          image_id,
                                                          volume_display_name)
            else:
                snapshot_id = c.create_snapshot(
                    volume_path, volume_display_name, volume_id, volume_name,
                    deletion_policy='DELETE_ON_ZERO_CLONE_REFERENCES')
            c.clone_volume(snapshot_id, clone_path)

        self._move_cloned_volume(clone_name, volume_id, share)

    def _update_volume_stats(self):
        """Retrieves stats info from volume group."""

        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.VENDOR
        data['vendor_name'] = self.VENDOR
        data['driver_version'] = self.get_version()
        data['storage_protocol'] = self.driver_volume_type

        self._ensure_shares_mounted()

        pools = []
        for share in self._mounted_shares:
            pool = dict()
            capacity, free, used = self._get_capacity_info(share)
            pool['pool_name'] = share
            pool['total_capacity_gb'] = capacity / float(units.Gi)
            pool['free_capacity_gb'] = free / float(units.Gi)
            pool['reserved_percentage'] = 0
            pool['QoS_support'] = True
            pools.append(pool)
        data['pools'] = pools

        self._stats = data

    def _get_provider_location(self, volume_id):
        """Returns provider location for given volume."""
        volume = self.db.volume_get(self._context, volume_id)
        return volume.provider_location

    def _get_host_ip(self, volume_id):
        """Returns IP address for the given volume."""
        return self._get_provider_location(volume_id).split(':')[0]

    def _get_export_path(self, volume_id):
        """Returns NFS export path for the given volume."""
        return self._get_provider_location(volume_id).split(':')[1]

    def _resolve_hostname(self, hostname):
        """Resolves host name to IP address."""
        res = socket.getaddrinfo(hostname, None)[0]
        family, socktype, proto, canonname, sockaddr = res
        return sockaddr[0]

    def _is_volume_present(self, volume_path):
        """Checks if volume exists."""
        try:
            self._execute('ls', volume_path,
                          run_as_root=self._execute_as_root)
        except Exception:
            return False
        return True

    def _get_volume_path(self, nfs_share, volume_name):
        """Gets local volume path for given volume name on given nfs share."""
        return os.path.join(self._get_mount_point_for_share(nfs_share),
                            volume_name)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        vol_size = volume.size
        src_vol_size = src_vref.size
        self._clone_volume_to_volume(src_vref.name, volume.name,
                                     src_vref.display_name,
                                     src_vref.id)

        share = self._get_provider_location(src_vref.id)
        volume['provider_location'] = share
        path = self.local_path(volume)

        self._set_rw_permissions(path)
        if vol_size != src_vol_size:
            try:
                self.extend_volume(volume, vol_size)
            except Exception:
                LOG.error(_LE('Resizing %s failed. Cleaning volume.'),
                          volume.name)
                self._delete_file(path)
                raise

        return {'provider_location': volume['provider_location']}

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetches the image from image_service and write it to the volume."""
        super(TintriDriver, self).copy_image_to_volume(
            context, volume, image_service, image_id)
        LOG.info(_LI('Copied image to volume %s using regular download.'),
                 volume['name'])
        self._create_image_snapshot(volume['name'],
                                    volume['provider_location'], image_id,
                                    img_prefix + image_id)

    def _create_image_snapshot(self, volume_name, share, image_id, image_name):
        """Creates an image snapshot."""
        snapshot_name = img_prefix + image_id
        LOG.info(_LI('Creating image snapshot %s'), snapshot_name)
        (host, path) = self._get_export_ip_path(None, share)
        volume_path = '%s/%s' % (path, volume_name)

        @utils.synchronized(snapshot_name, external=True)
        def _do_snapshot():
            with self._get_client() as c:
                snapshot_id = c.get_snapshot(image_id)
                if not snapshot_id:
                    snapshot_id = c.create_snapshot(volume_path, image_name,
                                                    image_id, snapshot_name)
                return snapshot_id

        try:
            return _do_snapshot()
        except Exception as e:
            LOG.warning(_LW('Exception while creating image %(image_id)s '
                            'snapshot. Exception: %(exc)s'),
                        {'image_id': image_id, 'exc': e})

    def _find_image_snapshot(self, image_id):
        """Finds image snapshot."""
        with self._get_client() as c:
            return c.get_snapshot(image_id)

    def _clone_image_snapshot(self, snapshot_id, dst, share):
        """Clones volume from image snapshot."""
        file_path = self._get_volume_path(share, dst)
        if not os.path.exists(file_path):
            LOG.info(_LI('Cloning from snapshot to destination %s'), dst)
            self._clone_snapshot(snapshot_id, dst, volume_id=None,
                                 share=share)

    def _delete_file(self, path):
        """Deletes file from disk and return result as boolean."""
        try:
            LOG.debug('Deleting file at path %s', path)
            cmd = ['rm', '-f', path]
            self._execute(*cmd, run_as_root=self._execute_as_root)
            return True
        except Exception as e:
            LOG.warning(_LW('Exception during deleting %s'), e)
            return False

    def _move_file(self, source_path, dest_path):
        """Moves source to destination."""

        @utils.synchronized(dest_path, external=True)
        def _do_move(src, dst):
            if os.path.exists(dst):
                LOG.warning(_LW('Destination %s already exists.'), dst)
                return False
            self._execute('mv', src, dst, run_as_root=self._execute_as_root)
            return True

        try:
            return _do_move(source_path, dest_path)
        except Exception as e:
            LOG.warning(_LW('Exception moving file %(src)s. Message: %(e)s'),
                        {'src': source_path, 'e': e})
        return False

    def clone_image(self, context, volume,
                    image_location, image_meta,
                    image_service):
        """Creates a volume efficiently from an existing image.

        image_location is a string whose format depends on the
        image service backend in use. The driver should use it
        to determine whether cloning is possible.

        Returns a dict of volume properties eg. provider_location,
        boolean indicating whether cloning occurred.
        """
        image_name = image_meta['name']
        image_id = image_meta['id']
        cloned = False
        post_clone = False
        try:
            snapshot_id = self._find_image_snapshot(image_id)
            if snapshot_id:
                cloned = self._clone_from_snapshot(volume, image_id,
                                                   snapshot_id)
            else:
                cloned = self._direct_clone(volume, image_location,
                                            image_id, image_name)
            if cloned:
                post_clone = self._post_clone_image(volume)
        except Exception as e:
            LOG.info(_LI('Image cloning unsuccessful for image '
                         '%(image_id)s. Message: %(msg)s'),
                     {'image_id': image_id, 'msg': e})
            vol_path = self.local_path(volume)
            volume['provider_location'] = None
            if os.path.exists(vol_path):
                self._delete_file(vol_path)
        finally:
            cloned = cloned and post_clone
            share = volume['provider_location'] if cloned else None
            bootable = True if cloned else False
            return {'provider_location': share, 'bootable': bootable}, cloned

    def _clone_from_snapshot(self, volume, image_id, snapshot_id):
        """Clones a copy from image snapshot."""
        cloned = False
        LOG.info(_LI('Cloning image %s from snapshot.'), image_id)
        for share in self._mounted_shares:
            # Repeat tries in other shares if failed in some
            LOG.debug('Image share: %s', share)
            if (share and
                    self._is_share_vol_compatible(volume, share)):
                try:
                    self._clone_image_snapshot(snapshot_id, volume['name'],
                                               share)
                    cloned = True
                    volume['provider_location'] = share
                    break
                except Exception:
                    LOG.warning(_LW('Unexpected exception during '
                                    'image cloning in share %s'), share)
        return cloned

    def _direct_clone(self, volume, image_location, image_id, image_name):
        """Clones directly in nfs share."""
        LOG.info(_LI('Checking image clone %s from glance share.'), image_id)
        cloned = False
        image_location = self._get_image_nfs_url(image_location)
        share = self._is_cloneable_share(image_location)
        run_as_root = self._execute_as_root

        if share and self._is_share_vol_compatible(volume, share):
            LOG.debug('Share is cloneable %s', share)
            volume['provider_location'] = share
            (__, ___, img_file) = image_location.rpartition('/')
            dir_path = self._get_mount_point_for_share(share)
            img_path = '%s/%s' % (dir_path, img_file)
            img_info = image_utils.qemu_img_info(img_path,
                                                 run_as_root=run_as_root)
            if img_info.file_format == 'raw':
                LOG.debug('Image is raw %s', image_id)
                self._clone_volume_to_volume(
                    img_file, volume['name'], image_name,
                    volume_id=None, share=share, image_id=image_id)
                cloned = True
            else:
                LOG.info(_LI('Image will locally be converted to raw %s'),
                         image_id)
                dst = '%s/%s' % (dir_path, volume['name'])
                image_utils.convert_image(img_path, dst, 'raw',
                                          run_as_root=run_as_root)
                data = image_utils.qemu_img_info(dst, run_as_root=run_as_root)
                if data.file_format != "raw":
                    raise exception.InvalidResults(
                        _('Converted to raw, but '
                          'format is now %s') % data.file_format)
                else:
                    cloned = True
                    self._create_image_snapshot(
                        volume['name'], volume['provider_location'],
                        image_id, image_name)
        return cloned

    def _post_clone_image(self, volume):
        """Performs operations post image cloning."""
        LOG.info(_LI('Performing post clone for %s'), volume['name'])
        vol_path = self.local_path(volume)
        self._set_rw_permissions(vol_path)
        self._resize_image_file(vol_path, volume['size'])
        return True

    def _resize_image_file(self, path, new_size):
        """Resizes the image file on share to new size."""
        LOG.debug('Checking file for resize.')
        if self._is_file_size_equal(path, new_size):
            return
        else:
            LOG.info(_LI('Resizing file to %sG'), new_size)
            image_utils.resize_image(path, new_size,
                                     run_as_root=self._execute_as_root)
            if self._is_file_size_equal(path, new_size):
                return
            else:
                raise exception.InvalidResults(
                    _('Resizing image file failed.'))

    def _is_cloneable_share(self, image_location):
        """Finds if the image at location is cloneable."""
        conn, dr = self._check_nfs_path(image_location)
        return self._is_share_in_use(conn, dr)

    def _check_nfs_path(self, image_location):
        """Checks if the nfs path format is matched.

        WebNFS url format with relative-path is supported.
        Accepting all characters in path-names and checking against
        the mounted shares which will contain only allowed path segments.
        Returns connection and dir details.
        """
        conn, dr = None, None
        if image_location:
            nfs_loc_pattern = \
                '^nfs://(([\w\-\.]+:[\d]+|[\w\-\.]+)(/[^/].*)*(/[^/\\\\]+))$'
            matched = re.match(nfs_loc_pattern, image_location)
            if not matched:
                LOG.debug('Image location not in the expected format %s',
                          image_location)
            else:
                conn = matched.group(2)
                dr = matched.group(3) or '/'
        return conn, dr

    def _is_share_in_use(self, conn, dr):
        """Checks if share is cinder mounted and returns it."""
        try:
            if conn:
                host = conn.split(':')[0]
                ip = self._resolve_hostname(host)
                for sh in self._mounted_shares:
                    sh_ip = self._resolve_hostname(sh.split(':')[0])
                    sh_exp = sh.split(':')[1]
                    if sh_ip == ip and sh_exp == dr:
                        LOG.debug('Found share match %s', sh)
                        return sh
        except Exception:
            LOG.warning(_LW('Unexpected exception while listing used share.'))

    def _get_image_nfs_url(self, image_location):
        """Gets direct url for nfs backend.

        It creates direct url from image_location
        which is a tuple with direct_url and locations.
        Returns url with nfs scheme if nfs store else returns url.
        It needs to be verified by backend before use.
        """

        direct_url, locations = image_location
        if not direct_url and not locations:
            raise exception.NotFound(_('Image location not present.'))

        # Locations will be always a list of one until
        # bp multiple-image-locations is introduced
        if not locations:
            return direct_url
        location = locations[0]
        url = location['url']
        if not location['metadata']:
            return url
        location_type = location['metadata'].get('type')
        if not location_type or location_type.lower() != "nfs":
            return url
        share_location = location['metadata'].get('share_location')
        mount_point = location['metadata'].get('mount_point')
        if not share_location or not mount_point:
            return url
        url_parse = urllib.parse.urlparse(url)
        abs_path = os.path.join(url_parse.netloc, url_parse.path)
        rel_path = os.path.relpath(abs_path, mount_point)
        direct_url = "%s/%s" % (share_location, rel_path)
        return direct_url

    def _is_share_vol_compatible(self, volume, share):
        """Checks if share is compatible with volume to host it."""
        return self._is_share_eligible(share, volume['size'])

    def _can_share_hold_size(self, share, size):
        """Checks if volume can hold image with size."""
        _tot_size, tot_available, _tot_allocated = self._get_capacity_info(
            share)
        if tot_available < size:
            msg = _('Container size smaller than required file size.')
            raise exception.VolumeDriverException(msg)

    def _get_export_ip_path(self, volume_id=None, share=None):
        """Returns export ip and path.

          One of volume id or share is used to return the values.
        """

        if volume_id:
            host_ip = self._get_host_ip(volume_id)
            export_path = self._get_export_path(volume_id)
        elif share:
            host_ip = share.split(':')[0]
            export_path = share.split(':')[1]
        else:
            raise exception.InvalidInput(
                reason=_('A volume ID or share was not specified.'))
        return host_ip, export_path

    def _get_local_path(self, volume_id=None, share=None):
        """Returns local path.

          One of volume id or share is used to return the values.
        """

        if volume_id:
            local_path = self._get_mount_point_for_share(
                self._get_provider_location(volume_id))
        elif share:
            local_path = self._get_mount_point_for_share(share)
        else:
            raise exception.InvalidInput(
                reason=_('A volume ID or share was not specified.'))
        return local_path

    def manage_existing(self, volume, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        existing_ref is passed straight through from the API request's
        manage_existing_ref value, and it is up to the driver how this should
        be interpreted.  It should be sufficient to identify a storage object
        that the driver should somehow associate with the newly-created cinder
        volume structure.

        :param volume:       Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume
        """
        nfs_share, nfs_mount, volume_name = self._get_share_mount(existing_ref)

        LOG.debug('Managing volume %(vol)s with ref %(ref)s',
                  {'vol': volume['id'], 'ref': existing_ref})
        if volume_name != volume['name']:
            src = os.path.join(nfs_mount, volume_name)
            dst = os.path.join(nfs_mount, volume['name'])
            if not self._move_file(src, dst):
                msg = (_('Failed to manage volume %s.') %
                       existing_ref['source-name'])
                raise exception.VolumeDriverException(msg)
            self._set_rw_permissions(dst)

        LOG.info(_LI('Manage volume %s'), volume['name'])
        return {'provider_location': nfs_share}

    def manage_existing_get_size(self, volume, existing_ref):
        """Returns size of volume to be managed by manage_existing.

        When calculating the size, round up to the next GB.

        :param volume:       Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume
        """
        nfs_share, nfs_mount, volume_name = self._get_share_mount(existing_ref)

        try:
            volume_path = os.path.join(nfs_mount, volume_name)
            vol_size = math.ceil(float(utils.get_file_size(volume_path)) /
                                 units.Gi)
        except OSError:
            msg = (_('Failed to get size of volume %s') %
                   existing_ref['source-name'])
            raise exception.VolumeDriverException(msg)

        return vol_size

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.

        :param volume: Cinder volume to unmanage
        """
        volume_path = self.local_path(volume)
        LOG.info(_LI('Unmanage volume %s'), volume_path)

    def _convert_volume_share(self, volume_share):
        """Converts the share name to IP address."""
        share_split = volume_share.rsplit(':', 1)
        return self._resolve_hostname(share_split[0]) + ':' + share_split[1]

    def _get_share_mount(self, vol_ref):
        """Get the NFS share, NFS mount, and volume path from reference.

        :param vol_ref: Driver-specific information used to identify a volume
        :return:        NFS Share, NFS mount, volume path
        """
        if 'source-name' not in vol_ref or not vol_ref['source-name']:
            msg = _('Volume reference must contain source-name element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=vol_ref, reason=msg)

        volume_share = self._convert_volume_share(vol_ref['source-name'])
        for nfs_share in self._mounted_shares:
            share = self._convert_volume_share(nfs_share)
            (__, match, volume_name) = volume_share.partition(share)
            if match == share:
                volume_name = volume_name.lstrip('/')
                nfs_mount = self._get_mount_point_for_share(nfs_share)
                volume_path = os.path.join(nfs_mount, volume_name)
                if os.path.isfile(volume_path):
                    LOG.debug('Found volume %(path)s on share %(share)s',
                              {'path': volume_path, 'share': nfs_share})
                    return nfs_share, nfs_mount, volume_name
                else:
                    LOG.debug('Volume ref %(ref)s not on share %(share)s',
                              {'ref': vol_ref, 'share': nfs_share})

        raise exception.ManageExistingInvalidReference(
            existing_ref=vol_ref, reason=_('Volume not found.'))


class TClient(object):
    """REST client for Tintri storage."""

    def __init__(self, hostname, username, password,
                 api_version=default_api_version):
        """Initializes a connection to Tintri server."""
        self.api_url = 'https://' + hostname + '/api'
        self.api_version = api_version
        self.session_id = self.login(username, password)
        self.headers = {'content-type': 'application/json',
                        'cookie': 'JSESSIONID=' + self.session_id}

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.logout()

    def get(self, api):
        return self.get_query(api, None)

    def get_query(self, api, query):
        url = self.api_url + api

        return requests.get(url, headers=self.headers,
                            params=query, verify=False)

    def delete(self, api):
        url = self.api_url + api

        return requests.delete(url, headers=self.headers, verify=False)

    def put(self, api, payload):
        url = self.api_url + api

        return requests.put(url, data=json.dumps(payload),
                            headers=self.headers, verify=False)

    def post(self, api, payload):
        url = self.api_url + api

        return requests.post(url, data=json.dumps(payload),
                             headers=self.headers, verify=False)

    def login(self, username, password):
        # Payload, header and URL for login
        headers = {'content-type': 'application/json',
                   'Tintri-Api-Client':
                   'Tintri-Cinder-Driver-%s' % TintriDriver.VERSION}
        payload = {'username': username,
                   'password': password,
                   'typeId': 'com.tintri.api.rest.vcommon.dto.rbac.'
                             'RestApiCredentials'}
        url = self.api_url + '/' + self.api_version + '/session/login'

        r = requests.post(url, data=json.dumps(payload),
                          headers=headers, verify=False)

        if r.status_code != 200:
            msg = _('Failed to login for user %s.') % username
            raise exception.VolumeDriverException(msg)

        return r.cookies['JSESSIONID']

    def logout(self):
        url = self.api_url + '/' + self.api_version + '/session/logout'

        requests.get(url, headers=self.headers, verify=False)

    @staticmethod
    def _remove_prefix(volume_path, prefix):
        if volume_path.startswith(prefix):
            return volume_path[len(prefix):]
        else:
            return volume_path

    def create_snapshot(self, volume_path, volume_name, volume_id,
                        snapshot_name, deletion_policy=None):
        """Creates a volume snapshot."""
        request = {'typeId': 'com.tintri.api.rest.' + self.api_version +
                             '.dto.domain.beans.cinder.CinderSnapshotSpec',
                   'file': TClient._remove_prefix(volume_path, tintri_path),
                   'vmName': volume_name or snapshot_name,
                   'description': snapshot_name + ' (' + volume_id + ')',
                   'vmTintriUuid': volume_id,
                   'instanceId': volume_id,
                   'snapshotCreator': 'Cinder',
                   'deletionPolicy': deletion_policy,
                   }

        payload = '/' + self.api_version + '/cinder/snapshot'
        r = self.post(payload, request)
        if r.status_code != 200:
            msg = _('Failed to create snapshot for volume %s.') % volume_path
            raise exception.VolumeDriverException(msg)

        return r.json()[0]

    def get_snapshot(self, volume_id):
        """Gets a volume snapshot."""
        filter = {'vmUuid': volume_id}

        payload = '/' + self.api_version + '/snapshot'
        r = self.get_query(payload, filter)
        if r.status_code != 200:
            msg = _('Failed to get snapshot for volume %s.') % volume_id
            raise exception.VolumeDriverException(msg)

        if int(r.json()['filteredTotal']) > 0:
            return r.json()['items'][0]['uuid']['uuid']

    def delete_snapshot(self, snapshot_uuid):
        """Deletes a snapshot."""
        url = '/' + self.api_version + '/snapshot/'
        self.delete(url + snapshot_uuid)

    def clone_volume(self, snapshot_uuid, volume_path):
        """Clones a volume from snapshot."""
        request = {'typeId': 'com.tintri.api.rest.' + self.api_version +
                             '.dto.domain.beans.cinder.CinderCloneSpec',
                   'destinationPaths':
                       [TClient._remove_prefix(volume_path, tintri_path)],
                   'tintriSnapshotUuid': snapshot_uuid,
                   }

        url = '/' + self.api_version + '/cinder/clone'
        r = self.post(url, request)
        if r.status_code != 200 and r.status_code != 204:
            msg = _('Failed to clone volume from snapshot %s.') % snapshot_uuid
            raise exception.VolumeDriverException(msg)
