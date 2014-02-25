# Copyright (c) 2012 NetApp, Inc.
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
"""
Volume driver for NetApp NFS storage.
"""

import copy
import os
import re
import socket
from threading import Timer
import time
import urlparse

from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder import units
from cinder import utils
from cinder.volume.drivers.netapp.api import NaApiError
from cinder.volume.drivers.netapp.api import NaElement
from cinder.volume.drivers.netapp.api import NaServer
from cinder.volume.drivers.netapp.options import netapp_basicauth_opts
from cinder.volume.drivers.netapp.options import netapp_cluster_opts
from cinder.volume.drivers.netapp.options import netapp_connection_opts
from cinder.volume.drivers.netapp.options import netapp_img_cache_opts
from cinder.volume.drivers.netapp.options import netapp_transport_opts
from cinder.volume.drivers.netapp import ssc_utils
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume.drivers.netapp.utils import get_volume_extra_specs
from cinder.volume.drivers.netapp.utils import provide_ems
from cinder.volume.drivers.netapp.utils import validate_instantiation
from cinder.volume.drivers import nfs


LOG = logging.getLogger(__name__)


class NetAppNFSDriver(nfs.NfsDriver):
    """Base class for NetApp NFS driver.
      Executes commands relating to Volumes.
    """

    VERSION = "1.0.0"

    def __init__(self, *args, **kwargs):
        # NOTE(vish): db is set by Manager
        validate_instantiation(**kwargs)
        self._execute = None
        self._context = None
        super(NetAppNFSDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(netapp_connection_opts)
        self.configuration.append_config_values(netapp_basicauth_opts)
        self.configuration.append_config_values(netapp_transport_opts)
        self.configuration.append_config_values(netapp_img_cache_opts)

    def set_execute(self, execute):
        self._execute = execute

    def do_setup(self, context):
        super(NetAppNFSDriver, self).do_setup(context)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        raise NotImplementedError()

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        vol_size = volume.size
        snap_size = snapshot.volume_size

        self._clone_volume(snapshot.name, volume.name, snapshot.volume_id)
        share = self._get_volume_location(snapshot.volume_id)
        volume['provider_location'] = share
        path = self.local_path(volume)

        if self._discover_file_till_timeout(path):
            self._set_rw_permissions_for_all(path)
            if vol_size != snap_size:
                try:
                    self.extend_volume(volume, vol_size)
                except Exception as e:
                    with excutils.save_and_reraise_exception():
                        LOG.error(
                            _("Resizing %s failed. Cleaning volume."),
                            volume.name)
                        self._execute('rm', path, run_as_root=True)
        else:
            raise exception.CinderException(
                _("NFS file %s not discovered.") % volume['name'])

        return {'provider_location': volume['provider_location']}

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self._clone_volume(snapshot['volume_name'],
                           snapshot['name'],
                           snapshot['volume_id'])

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        nfs_mount = self._get_provider_location(snapshot.volume_id)

        if self._volume_not_present(nfs_mount, snapshot.name):
            return True

        self._execute('rm', self._get_volume_path(nfs_mount, snapshot.name),
                      run_as_root=True)

    def _get_client(self):
        """Creates client for server."""
        raise NotImplementedError()

    def _get_volume_location(self, volume_id):
        """Returns NFS mount address as <nfs_ip_address>:<nfs_mount_dir>."""
        nfs_server_ip = self._get_host_ip(volume_id)
        export_path = self._get_export_path(volume_id)
        return (nfs_server_ip + ':' + export_path)

    def _clone_volume(self, volume_name, clone_name, volume_id, share=None):
        """Clones mounted volume using NetApp api."""
        raise NotImplementedError()

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

    def _volume_not_present(self, nfs_mount, volume_name):
        """Check if volume exists."""
        try:
            self._try_execute('ls', self._get_volume_path(nfs_mount,
                                                          volume_name))
        except processutils.ProcessExecutionError:
            # If the volume isn't present
            return True
        return False

    def _try_execute(self, *command, **kwargs):
        # NOTE(vish): Volume commands can partially fail due to timing, but
        #             running them a second time on failure will usually
        #             recover nicely.
        tries = 0
        while True:
            try:
                self._execute(*command, **kwargs)
                return True
            except processutils.ProcessExecutionError:
                tries = tries + 1
                if tries >= self.configuration.num_shell_tries:
                    raise
                LOG.exception(_("Recovering from a failed execute.  "
                                "Try number %s"), tries)
                time.sleep(tries ** 2)

    def _get_volume_path(self, nfs_share, volume_name):
        """Get volume path (local fs path) for given volume name on given nfs
        share.

        @param nfs_share string, example 172.18.194.100:/var/nfs
        @param volume_name string,
            example volume-91ee65ec-c473-4391-8c09-162b00c68a8c
        """

        return os.path.join(self._get_mount_point_for_share(nfs_share),
                            volume_name)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        vol_size = volume.size
        src_vol_size = src_vref.size
        self._clone_volume(src_vref.name, volume.name, src_vref.id)
        share = self._get_volume_location(src_vref.id)
        volume['provider_location'] = share
        path = self.local_path(volume)

        if self._discover_file_till_timeout(path):
            self._set_rw_permissions_for_all(path)
            if vol_size != src_vol_size:
                try:
                    self.extend_volume(volume, vol_size)
                except Exception as e:
                    LOG.error(
                        _("Resizing %s failed. Cleaning volume."), volume.name)
                    self._execute('rm', path, run_as_root=True)
                    raise e
        else:
            raise exception.CinderException(
                _("NFS file %s not discovered.") % volume['name'])

        return {'provider_location': volume['provider_location']}

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""
        super(NetAppNFSDriver, self)._update_volume_stats()
        self._spawn_clean_cache_job()

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        super(NetAppNFSDriver, self).copy_image_to_volume(
            context, volume, image_service, image_id)
        LOG.info(_('Copied image to volume %s'), volume['name'])
        self._register_image_in_cache(volume, image_id)

    def _register_image_in_cache(self, volume, image_id):
        """Stores image in the cache."""
        file_name = 'img-cache-%s' % image_id
        LOG.info(_("Registering image in cache %s"), file_name)
        try:
            self._do_clone_rel_img_cache(
                volume['name'], file_name,
                volume['provider_location'], file_name)
        except Exception as e:
            LOG.warn(
                _('Exception while registering image %(image_id)s'
                  ' in cache. Exception: %(exc)s')
                % {'image_id': image_id, 'exc': e.__str__()})

    def _find_image_in_cache(self, image_id):
        """Finds image in cache and returns list of shares with file name."""
        result = []
        if getattr(self, '_mounted_shares', None):
            for share in self._mounted_shares:
                dir = self._get_mount_point_for_share(share)
                file_name = 'img-cache-%s' % image_id
                file_path = '%s/%s' % (dir, file_name)
                if os.path.exists(file_path):
                    LOG.debug(_('Found cache file for image %(image_id)s'
                                ' on share %(share)s')
                              % {'image_id': image_id, 'share': share})
                    result.append((share, file_name))
        return result

    def _do_clone_rel_img_cache(self, src, dst, share, cache_file):
        """Do clone operation w.r.t image cache file."""
        @utils.synchronized(cache_file, external=True)
        def _do_clone():
            dir = self._get_mount_point_for_share(share)
            file_path = '%s/%s' % (dir, dst)
            if not os.path.exists(file_path):
                LOG.info(_('Cloning img from cache for %s'), dst)
                self._clone_volume(src, dst, volume_id=None, share=share)
        _do_clone()

    @utils.synchronized('clean_cache')
    def _spawn_clean_cache_job(self):
        """Spawns a clean task if not running."""
        if getattr(self, 'cleaning', None):
                LOG.debug(_('Image cache cleaning in progress. Returning... '))
                return
        else:
                #set cleaning to True
                self.cleaning = True
                t = Timer(0, self._clean_image_cache)
                t.start()

    def _clean_image_cache(self):
        """Clean the image cache files in cache of space crunch."""
        try:
            LOG.debug(_('Image cache cleaning in progress.'))
            thres_size_perc_start =\
                self.configuration.thres_avl_size_perc_start
            thres_size_perc_stop =\
                self.configuration.thres_avl_size_perc_stop
            for share in getattr(self, '_mounted_shares', []):
                try:
                    total_size, total_avl, total_alc =\
                        self._get_capacity_info(share)
                    avl_percent = int((total_avl / total_size) * 100)
                    if avl_percent <= thres_size_perc_start:
                        LOG.info(_('Cleaning cache for share %s.'), share)
                        eligible_files = self._find_old_cache_files(share)
                        threshold_size = int(
                            (thres_size_perc_stop * total_size) / 100)
                        bytes_to_free = int(threshold_size - total_avl)
                        LOG.debug(_('Files to be queued for deletion %s'),
                                  eligible_files)
                        self._delete_files_till_bytes_free(
                            eligible_files, share, bytes_to_free)
                    else:
                        continue
                except Exception as e:
                    LOG.warn(_(
                        'Exception during cache cleaning'
                        ' %(share)s. Message - %(ex)s')
                        % {'share': share, 'ex': e.__str__()})
                    continue
        finally:
            LOG.debug(_('Image cache cleaning done.'))
            self.cleaning = False

    def _shortlist_del_eligible_files(self, share, old_files):
        """Prepares list of eligible files to be deleted from cache."""
        raise NotImplementedError()

    def _find_old_cache_files(self, share):
        """Finds the old files in cache."""
        mount_fs = self._get_mount_point_for_share(share)
        threshold_minutes = self.configuration.expiry_thres_minutes
        cmd = ['find', mount_fs, '-maxdepth', '1', '-name',
               'img-cache*', '-amin', '+%s' % (threshold_minutes)]
        res, __ = self._execute(*cmd, run_as_root=True)
        if res:
            old_file_paths = res.strip('\n').split('\n')
            mount_fs_len = len(mount_fs)
            old_files = [x[mount_fs_len + 1:] for x in old_file_paths]
            eligible_files = self._shortlist_del_eligible_files(
                share, old_files)
            return eligible_files
        return []

    def _delete_files_till_bytes_free(self, file_list, share, bytes_to_free=0):
        """Delete files from disk till bytes are freed or list exhausted."""
        LOG.debug(_('Bytes to free %s'), bytes_to_free)
        if file_list and bytes_to_free > 0:
            sorted_files = sorted(file_list, key=lambda x: x[1], reverse=True)
            mount_fs = self._get_mount_point_for_share(share)
            for f in sorted_files:
                if f:
                    file_path = '%s/%s' % (mount_fs, f[0])
                    LOG.debug(_('Delete file path %s'), file_path)

                    @utils.synchronized(f[0], external=True)
                    def _do_delete():
                        if self._delete_file(file_path):
                            return True
                        return False
                    if _do_delete():
                            bytes_to_free = bytes_to_free - int(f[1])
                            if bytes_to_free <= 0:
                                return

    def _delete_file(self, path):
        """Delete file from disk and return result as boolean."""
        try:
            LOG.debug(_('Deleting file at path %s'), path)
            cmd = ['rm', '-f', path]
            self._execute(*cmd, run_as_root=True)
            return True
        except Exception as ex:
            LOG.warning(_('Exception during deleting %s'), ex.__str__())
            return False

    def clone_image(self, volume, image_location, image_id, image_meta):
        """Create a volume efficiently from an existing image.

        image_location is a string whose format depends on the
        image service backend in use. The driver should use it
        to determine whether cloning is possible.

        image_id is a string which represents id of the image.
        It can be used by the driver to introspect internal
        stores or registry to do an efficient image clone.

        Returns a dict of volume properties eg. provider_location,
        boolean indicating whether cloning occurred.
        """

        cloned = False
        post_clone = False
        share = None
        try:
            cache_result = self._find_image_in_cache(image_id)
            if cache_result:
                cloned = self._clone_from_cache(volume, image_id, cache_result)
            else:
                cloned = self._direct_nfs_clone(volume, image_location,
                                                image_id)
            if cloned:
                post_clone = self._post_clone_image(volume)
        except Exception as e:
            msg = e.msg if getattr(e, 'msg', None) else e.__str__()
            LOG.warn(_('Unexpected exception in cloning image'
                       ' %(image_id)s. Message: %(msg)s')
                     % {'image_id': image_id, 'msg': msg})
            vol_path = self.local_path(volume)
            volume['provider_location'] = None
            if os.path.exists(vol_path):
                self._delete_file(vol_path)
        finally:
            cloned = cloned and post_clone
            share = volume['provider_location'] if cloned else None
            bootable = True if cloned else False
            return {'provider_location': share, 'bootable': bootable}, cloned

    def _clone_from_cache(self, volume, image_id, cache_result):
        """Clones a copy from image cache."""
        cloned = False
        LOG.info(_('Cloning image %s from cache'), image_id)
        for res in cache_result:
            # Repeat tries in other shares if failed in some
            (share, file_name) = res
            LOG.debug(_('Cache share: %s'), share)
            if (share and
                    self._is_share_vol_compatible(volume, share)):
                try:
                    self._do_clone_rel_img_cache(
                        file_name, volume['name'], share, file_name)
                    cloned = True
                    volume['provider_location'] = share
                    break
                except Exception:
                    LOG.warn(_('Unexpected exception during'
                               ' image cloning in share %s'), share)
        return cloned

    def _direct_nfs_clone(self, volume, image_location, image_id):
        """Clone directly in nfs share."""
        LOG.info(_('Cloning image %s directly in share'), image_id)
        cloned = False
        image_location = self._construct_image_nfs_url(image_location)
        share = self._is_cloneable_share(image_location)
        if share and self._is_share_vol_compatible(volume, share):
            LOG.debug(_('Share is cloneable %s'), share)
            volume['provider_location'] = share
            (__, ___, img_file) = image_location.rpartition('/')
            dir_path = self._get_mount_point_for_share(share)
            img_path = '%s/%s' % (dir_path, img_file)
            img_info = image_utils.qemu_img_info(img_path)
            if img_info.file_format == 'raw':
                LOG.debug(_('Image is raw %s'), image_id)
                self._clone_volume(
                    img_file, volume['name'],
                    volume_id=None, share=share)
                cloned = True
            else:
                LOG.info(
                    _('Image will locally be converted to raw %s'),
                    image_id)
                dst = '%s/%s' % (dir_path, volume['name'])
                image_utils.convert_image(img_path, dst, 'raw')
                data = image_utils.qemu_img_info(dst)
                if data.file_format != "raw":
                    raise exception.InvalidResults(
                        _("Converted to raw, but"
                            " format is now %s") % data.file_format)
                else:
                    cloned = True
                    self._register_image_in_cache(
                        volume, image_id)
        return cloned

    def _post_clone_image(self, volume):
        """Do operations post image cloning."""
        LOG.info(_('Performing post clone for %s'), volume['name'])
        vol_path = self.local_path(volume)
        if self._discover_file_till_timeout(vol_path):
            self._set_rw_permissions_for_all(vol_path)
            self._resize_image_file(vol_path, volume['size'])
            return True
        raise exception.InvalidResults(
            _("NFS file could not be discovered."))

    def _resize_image_file(self, path, new_size):
        """Resize the image file on share to new size."""
        LOG.debug(_('Checking file for resize'))
        if self._is_file_size_equal(path, new_size):
            return
        else:
            LOG.info(_('Resizing file to %sG'), new_size)
            image_utils.resize_image(path, new_size)
            if self._is_file_size_equal(path, new_size):
                return
            else:
                raise exception.InvalidResults(
                    _('Resizing image file failed.'))

    def _is_file_size_equal(self, path, size):
        """Checks if file size at path is equal to size."""
        data = image_utils.qemu_img_info(path)
        virt_size = data.virtual_size / units.GiB
        if virt_size == size:
            return True
        else:
            return False

    def _discover_file_till_timeout(self, path, timeout=45):
        """Checks if file size at path is equal to size."""
        # Sometimes nfs takes time to discover file
        # Retrying in case any unexpected situation occurs
        retry_seconds = timeout
        sleep_interval = 2
        while True:
            if os.path.exists(path):
                return True
            else:
                if retry_seconds <= 0:
                    LOG.warn(_('Discover file retries exhausted.'))
                    return False
                else:
                    time.sleep(sleep_interval)
                    retry_seconds = retry_seconds - sleep_interval

    def _is_cloneable_share(self, image_location):
        """Finds if the image at location is cloneable.

             WebNFS url format with relative-path is supported.
             Accepting all characters in path-names and checking
             against the mounted shares which will contain only
             allowed path segments.
        """

        nfs_loc_pattern =\
            '^nfs://(([\w\-\.]+:{1}[\d]+|[\w\-\.]+)(/[^\/].*)*(/[^\/\\\\]+)$)'
        matched = re.match(nfs_loc_pattern, image_location, flags=0)
        if not matched:
            LOG.debug(_('Image location not in the'
                        ' expected format %s'), image_location)
            return None
        conn = matched.group(2)
        dir = matched.group(3) or '/'
        return self._check_share_in_use(conn, dir)

    def _share_match_for_ip(self, ip, shares):
        """Returns the share that is served by ip.

            Multiple shares can have same dir path but
            can be served using different ips. It finds the
            share which is served by ip on same nfs server.
        """
        raise NotImplementedError()

    def _check_share_in_use(self, conn, dir):
        """Checks if share is cinder mounted and returns it."""
        try:
            if conn:
                host = conn.split(':')[0]
                ip = self._resolve_hostname(host)
                share_candidates = []
                for sh in self._mounted_shares:
                    sh_exp = sh.split(':')[1]
                    if sh_exp == dir:
                        share_candidates.append(sh)
                if share_candidates:
                    LOG.debug(_('Found possible share matches %s'),
                              share_candidates)
                    return self._share_match_for_ip(ip, share_candidates)
        except Exception:
            LOG.warn(_("Unexpected exception while short listing used share."))
        return None

    def _construct_image_nfs_url(self, image_location):
        """Construct direct url for nfs backend.

             It creates direct url from image_location
             which is a tuple with direct_url and locations.
             Returns url with nfs scheme if nfs store
             else returns url. It needs to be verified
             by backend before use.
        """

        direct_url, locations = image_location

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
        url_parse = urlparse.urlparse(url)
        abs_path = os.path.join(url_parse.netloc, url_parse.path)
        rel_path = os.path.relpath(abs_path, mount_point)
        direct_url = "%s/%s" % (share_location, rel_path)
        return direct_url

    def extend_volume(self, volume, new_size):
        """Extend an existing volume to the new size."""
        LOG.info(_('Extending volume %s.'), volume['name'])
        path = self.local_path(volume)
        self._resize_image_file(path, new_size)

    def _is_share_vol_compatible(self, volume, share):
        """Checks if share is compatible with volume to host it."""
        raise NotImplementedError()

    def _resolve_hostname(self, hostname):
        """Resolves hostname to IP address."""
        res = socket.getaddrinfo(hostname, None)[0]
        family, socktype, proto, canonname, sockaddr = res
        return sockaddr[0]


class NetAppDirectNfsDriver (NetAppNFSDriver):
    """Executes commands related to volumes on NetApp filer."""

    def __init__(self, *args, **kwargs):
        super(NetAppDirectNfsDriver, self).__init__(*args, **kwargs)

    def do_setup(self, context):
        super(NetAppDirectNfsDriver, self).do_setup(context)
        self._context = context
        self._client = self._get_client()
        self._do_custom_setup(self._client)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        self._check_flags()

    def _check_flags(self):
        """Raises error if any required configuration flag is missing."""
        required_flags = ['netapp_login',
                          'netapp_password',
                          'netapp_server_hostname',
                          'netapp_server_port',
                          'netapp_transport_type']
        for flag in required_flags:
            if not getattr(self.configuration, flag, None):
                raise exception.CinderException(_('%s is not set') % flag)

    def _get_client(self):
        """Creates NetApp api client."""
        client = NaServer(
            host=self.configuration.netapp_server_hostname,
            server_type=NaServer.SERVER_TYPE_FILER,
            transport_type=self.configuration.netapp_transport_type,
            style=NaServer.STYLE_LOGIN_PASSWORD,
            username=self.configuration.netapp_login,
            password=self.configuration.netapp_password)
        return client

    def _do_custom_setup(self, client):
        """Do the customized set up on client if any for different types."""
        raise NotImplementedError()

    def _is_naelement(self, elem):
        """Checks if element is NetApp element."""
        if not isinstance(elem, NaElement):
            raise ValueError('Expects NaElement')

    def _get_ontapi_version(self):
        """Gets the supported ontapi version."""
        ontapi_version = NaElement('system-get-ontapi-version')
        res = self._client.invoke_successfully(ontapi_version, False)
        major = res.get_child_content('major-version')
        minor = res.get_child_content('minor-version')
        return (major, minor)

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
            raise exception.InvalidInput('None of vol id or share specified.')
        return (host_ip, export_path)

    def _create_file_usage_req(self, path):
        """Creates the request element for file_usage_get."""
        file_use = NaElement.create_node_with_children(
            'file-usage-get', **{'path': path})
        return file_use


class NetAppDirectCmodeNfsDriver (NetAppDirectNfsDriver):
    """Executes commands related to volumes on c mode."""

    def __init__(self, *args, **kwargs):
        super(NetAppDirectCmodeNfsDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(netapp_cluster_opts)

    def _do_custom_setup(self, client):
        """Do the customized set up on client for cluster mode."""
        # Default values to run first api
        client.set_api_version(1, 15)
        (major, minor) = self._get_ontapi_version()
        client.set_api_version(major, minor)
        self.vserver = self.configuration.netapp_vserver
        self.ssc_vols = None
        self.stale_vols = set()
        if self.vserver:
            self.ssc_enabled = True
            LOG.info(_("Shares on vserver %s will only"
                       " be used for provisioning.") % (self.vserver))
        else:
            self.ssc_enabled = False
            LOG.warn(_("No vserver set in config. SSC will be disabled."))

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate."""
        super(NetAppDirectCmodeNfsDriver, self).check_for_setup_error()
        if self.ssc_enabled:
            ssc_utils.check_ssc_api_permissions(self._client)

    def _invoke_successfully(self, na_element, vserver=None):
        """Invoke the api for successful result.

        If vserver is present then invokes vserver api
        else Cluster api.
        :param vserver: vserver name.
        """

        self._is_naelement(na_element)
        server = copy.copy(self._client)
        if vserver:
            server.set_vserver(vserver)
        else:
            server.set_vserver(None)
        result = server.invoke_successfully(na_element, True)
        return result

    def create_volume(self, volume):
        """Creates a volume.

        :param volume: volume reference
        """
        self._ensure_shares_mounted()
        extra_specs = get_volume_extra_specs(volume)
        eligible = self._find_shares(volume['size'], extra_specs)
        if not eligible:
            raise exception.NfsNoSuitableShareFound(
                volume_size=volume['size'])
        for sh in eligible:
            try:
                volume['provider_location'] = sh
                LOG.info(_('casted to %s') % volume['provider_location'])
                self._do_create_volume(volume)
                return {'provider_location': volume['provider_location']}
            except Exception:
                LOG.warn(_("Exception creating vol %(name)s"
                           " on share %(share)s")
                         % {'name': volume['name'],
                             'share': volume['provider_location']})
                volume['provider_location'] = None
            finally:
                if self.ssc_enabled:
                    self._update_stale_vols(self._get_vol_for_share(sh))
        msg = _("Volume %s could not be created on shares.")
        raise exception.VolumeBackendAPIException(data=msg % (volume['name']))

    def _find_shares(self, size, extra_specs):
        """Finds suitable shares for given params."""
        shares = []
        containers = []
        if self.ssc_enabled:
            vols = ssc_utils.get_volumes_for_specs(self.ssc_vols, extra_specs)
            containers = [x.export['path'] for x in vols]
        else:
            containers = self._mounted_shares
        for sh in containers:
            if self._is_share_eligible(sh, size):
                size, avl, alloc = self._get_capacity_info(sh)
                shares.append((sh, avl))
        shares = [a for a, b in sorted(
            shares, key=lambda x: x[1], reverse=True)]
        return shares

    def _clone_volume(self, volume_name, clone_name,
                      volume_id, share=None):
        """Clones mounted volume on NetApp Cluster."""
        (vserver, exp_volume) = self._get_vserver_and_exp_vol(volume_id, share)
        self._clone_file(exp_volume, volume_name, clone_name, vserver)
        share = share if share else self._get_provider_location(volume_id)
        self._post_prov_deprov_in_ssc(share)

    def _get_vserver_and_exp_vol(self, volume_id=None, share=None):
        """Gets the vserver and export volume for share."""
        (host_ip, export_path) = self._get_export_ip_path(volume_id, share)
        ifs = self._get_if_info_by_ip(host_ip)
        vserver = ifs[0].get_child_content('vserver')
        exp_volume = self._get_vol_by_junc_vserver(vserver, export_path)
        return (vserver, exp_volume)

    def _get_if_info_by_ip(self, ip):
        """Gets the network interface info by ip."""
        net_if_iter = NaElement('net-interface-get-iter')
        net_if_iter.add_new_child('max-records', '10')
        query = NaElement('query')
        net_if_iter.add_child_elem(query)
        query.add_node_with_children('net-interface-info',
                                     **{'address': self._resolve_hostname(ip)})
        result = self._invoke_successfully(net_if_iter)
        if result.get_child_content('num-records') and\
                int(result.get_child_content('num-records')) >= 1:
            attr_list = result.get_child_by_name('attributes-list')
            return attr_list.get_children()
        raise exception.NotFound(
            _('No interface found on cluster for ip %s')
            % (ip))

    def _get_vserver_ips(self, vserver):
        """Get ips for the vserver."""
        result = na_utils.invoke_api(
            self._client, api_name='net-interface-get-iter',
            is_iter=True, tunnel=vserver)
        if_list = []
        for res in result:
            records = res.get_child_content('num-records')
            if records > 0:
                attr_list = res['attributes-list']
                ifs = attr_list.get_children()
                if_list.extend(ifs)
        return if_list

    def _get_vol_by_junc_vserver(self, vserver, junction):
        """Gets the volume by junction path and vserver."""
        vol_iter = NaElement('volume-get-iter')
        vol_iter.add_new_child('max-records', '10')
        query = NaElement('query')
        vol_iter.add_child_elem(query)
        vol_attrs = NaElement('volume-attributes')
        query.add_child_elem(vol_attrs)
        vol_attrs.add_node_with_children(
            'volume-id-attributes',
            **{'junction-path': junction,
                'owning-vserver-name': vserver})
        des_attrs = NaElement('desired-attributes')
        des_attrs.add_node_with_children('volume-attributes',
                                         **{'volume-id-attributes': None})
        vol_iter.add_child_elem(des_attrs)
        result = self._invoke_successfully(vol_iter, vserver)
        if result.get_child_content('num-records') and\
                int(result.get_child_content('num-records')) >= 1:
            attr_list = result.get_child_by_name('attributes-list')
            vols = attr_list.get_children()
            vol_id = vols[0].get_child_by_name('volume-id-attributes')
            return vol_id.get_child_content('name')
        msg_fmt = {'vserver': vserver, 'junction': junction}
        raise exception.NotFound(_("""No volume on cluster with vserver
                                   %(vserver)s and junction path %(junction)s
                                   """) % msg_fmt)

    def _clone_file(self, volume, src_path, dest_path, vserver=None):
        """Clones file on vserver."""
        msg = _("""Cloning with params volume %(volume)s, src %(src_path)s,
                    dest %(dest_path)s, vserver %(vserver)s""")
        msg_fmt = {'volume': volume, 'src_path': src_path,
                   'dest_path': dest_path, 'vserver': vserver}
        LOG.debug(msg % msg_fmt)
        clone_create = NaElement.create_node_with_children(
            'clone-create',
            **{'volume': volume, 'source-path': src_path,
                'destination-path': dest_path})
        self._invoke_successfully(clone_create, vserver)

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""
        super(NetAppDirectCmodeNfsDriver, self)._update_volume_stats()
        netapp_backend = 'NetApp_NFS_cluster_direct'
        backend_name = self.configuration.safe_get('volume_backend_name')
        self._stats["volume_backend_name"] = (backend_name or
                                              netapp_backend)
        self._stats["vendor_name"] = 'NetApp'
        self._stats["driver_version"] = '1.0'
        self._update_cluster_vol_stats(self._stats)
        provide_ems(self, self._client, self._stats, netapp_backend)

    def _update_cluster_vol_stats(self, data):
        """Updates vol stats with cluster config."""
        if self.ssc_enabled:
            sync = True if self.ssc_vols is None else False
            ssc_utils.refresh_cluster_ssc(self, self._client, self.vserver,
                                          synchronous=sync)
        else:
            LOG.warn(_("No vserver set in config. SSC will be disabled."))
        if self.ssc_vols:
            data['netapp_mirrored'] = 'true'\
                if self.ssc_vols['mirrored'] else 'false'
            data['netapp_unmirrored'] = 'true'\
                if len(self.ssc_vols['all']) >\
                len(self.ssc_vols['mirrored']) else 'false'
            data['netapp_dedup'] = 'true'\
                if self.ssc_vols['dedup'] else 'false'
            data['netapp_nodedup'] = 'true'\
                if len(self.ssc_vols['all']) >\
                len(self.ssc_vols['dedup']) else 'false'
            data['netapp_compression'] = 'true'\
                if self.ssc_vols['compression'] else 'false'
            data['netapp_nocompression'] = 'true'\
                if len(self.ssc_vols['all']) >\
                len(self.ssc_vols['compression']) else 'false'
            data['netapp_thin_provisioned'] = 'true'\
                if self.ssc_vols['thin'] else 'false'
            data['netapp_thick_provisioned'] = 'true'\
                if len(self.ssc_vols['all']) >\
                len(self.ssc_vols['thin']) else 'false'
            if self.ssc_vols['all']:
                vol_max = max(self.ssc_vols['all'])
                data['total_capacity_gb'] =\
                    int(vol_max.space['size_total_bytes']) / units.GiB
                data['free_capacity_gb'] =\
                    int(vol_max.space['size_avl_bytes']) / units.GiB
            else:
                data['total_capacity_gb'] = 0
                data['free_capacity_gb'] = 0
        elif self.ssc_enabled:
            LOG.warn(_("No cluster ssc stats found."
                       " Wait for next volume stats update."))

    @utils.synchronized('update_stale')
    def _update_stale_vols(self, volume=None, reset=False):
        """Populates stale vols with vol and returns set copy."""
        if volume:
            self.stale_vols.add(volume)
        set_copy = self.stale_vols.copy()
        if reset:
            self.stale_vols.clear()
        return set_copy

    @utils.synchronized("refresh_ssc_vols")
    def refresh_ssc_vols(self, vols):
        """Refreshes ssc_vols with latest entries."""
        if not self._mounted_shares:
            LOG.warn(_("No shares found hence skipping ssc refresh."))
            return
        mnt_share_vols = set()
        vs_ifs = self._get_vserver_ips(self.vserver)
        for vol in vols['all']:
            for sh in self._mounted_shares:
                host = sh.split(':')[0]
                junction = sh.split(':')[1]
                ip = self._resolve_hostname(host)
                if (self._ip_in_ifs(ip, vs_ifs) and
                        junction == vol.id['junction_path']):
                    mnt_share_vols.add(vol)
                    vol.export['path'] = sh
                    break
        for key in vols.keys():
            vols[key] = vols[key] & mnt_share_vols
        self.ssc_vols = vols

    def _ip_in_ifs(self, ip, api_ifs):
        """Checks if ip is listed for ifs in api format."""
        if api_ifs is None:
            return False
        for ifc in api_ifs:
            ifc_ip = ifc.get_child_content("address")
            if ifc_ip == ip:
                return True
        return False

    def _shortlist_del_eligible_files(self, share, old_files):
        """Prepares list of eligible files to be deleted from cache."""
        file_list = []
        (vserver, exp_volume) = self._get_vserver_and_exp_vol(
            volume_id=None, share=share)
        for file in old_files:
            path = '/vol/%s/%s' % (exp_volume, file)
            u_bytes = self._get_cluster_file_usage(path, vserver)
            file_list.append((file, u_bytes))
        LOG.debug(_('Shortlisted del elg files %s'), file_list)
        return file_list

    def _get_cluster_file_usage(self, path, vserver):
        """Gets the file unique bytes."""
        LOG.debug(_('Getting file usage for %s'), path)
        file_use = NaElement.create_node_with_children(
            'file-usage-get', **{'path': path})
        res = self._invoke_successfully(file_use, vserver)
        bytes = res.get_child_content('unique-bytes')
        LOG.debug(_('file-usage for path %(path)s is %(bytes)s')
                  % {'path': path, 'bytes': bytes})
        return bytes

    def _share_match_for_ip(self, ip, shares):
        """Returns the share that is served by ip.

            Multiple shares can have same dir path but
            can be served using different ips. It finds the
            share which is served by ip on same nfs server.
        """
        ip_vserver = self._get_vserver_for_ip(ip)
        if ip_vserver and shares:
            for share in shares:
                ip_sh = share.split(':')[0]
                sh_vserver = self._get_vserver_for_ip(ip_sh)
                if sh_vserver == ip_vserver:
                    LOG.debug(_('Share match found for ip %s'), ip)
                    return share
        LOG.debug(_('No share match found for ip %s'), ip)
        return None

    def _get_vserver_for_ip(self, ip):
        """Get vserver for the mentioned ip."""
        try:
            ifs = self._get_if_info_by_ip(ip)
            vserver = ifs[0].get_child_content('vserver')
            return vserver
        except Exception:
            return None

    def _get_vol_for_share(self, nfs_share):
        """Gets the ssc vol with given share."""
        if self.ssc_vols:
            for vol in self.ssc_vols['all']:
                if vol.export['path'] == nfs_share:
                    return vol
        return None

    def _is_share_vol_compatible(self, volume, share):
        """Checks if share is compatible with volume to host it."""
        compatible = self._is_share_eligible(share, volume['size'])
        if compatible and self.ssc_enabled:
            matched = self._is_share_vol_type_match(volume, share)
            compatible = compatible and matched
        return compatible

    def _is_share_vol_type_match(self, volume, share):
        """Checks if share matches volume type."""
        netapp_vol = self._get_vol_for_share(share)
        LOG.debug(_("Found volume %(vol)s for share %(share)s.")
                  % {'vol': netapp_vol, 'share': share})
        extra_specs = get_volume_extra_specs(volume)
        vols = ssc_utils.get_volumes_for_specs(self.ssc_vols, extra_specs)
        return netapp_vol in vols

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        share = volume['provider_location']
        super(NetAppDirectCmodeNfsDriver, self).delete_volume(volume)
        self._post_prov_deprov_in_ssc(share)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        share = self._get_provider_location(snapshot.volume_id)
        super(NetAppDirectCmodeNfsDriver, self).delete_snapshot(snapshot)
        self._post_prov_deprov_in_ssc(share)

    def _post_prov_deprov_in_ssc(self, share):
        if self.ssc_enabled and share:
            netapp_vol = self._get_vol_for_share(share)
            if netapp_vol:
                self._update_stale_vols(volume=netapp_vol)


class NetAppDirect7modeNfsDriver (NetAppDirectNfsDriver):
    """Executes commands related to volumes on 7 mode."""

    def __init__(self, *args, **kwargs):
        super(NetAppDirect7modeNfsDriver, self).__init__(*args, **kwargs)

    def _do_custom_setup(self, client):
        """Do the customized set up on client if any for 7 mode."""
        (major, minor) = self._get_ontapi_version()
        client.set_api_version(major, minor)

    def check_for_setup_error(self):
        """Checks if setup occurred properly."""
        api_version = self._client.get_api_version()
        if api_version:
            major, minor = api_version
            if major == 1 and minor < 9:
                msg = _("Unsupported ONTAP version."
                        " ONTAP version 7.3.1 and above is supported.")
                raise exception.VolumeBackendAPIException(data=msg)
        else:
            msg = _("Api version could not be determined.")
            raise exception.VolumeBackendAPIException(data=msg)
        super(NetAppDirect7modeNfsDriver, self).check_for_setup_error()

    def _invoke_successfully(self, na_element, vfiler=None):
        """Invoke the api for successful result.

        If vfiler is present then invokes vfiler api
        else filer api.
        :param vfiler: vfiler name.
        """

        self._is_naelement(na_element)
        server = copy.copy(self._client)
        if vfiler:
            server.set_vfiler(vfiler)
        else:
            server.set_vfiler(None)
        result = server.invoke_successfully(na_element, True)
        return result

    def _clone_volume(self, volume_name, clone_name,
                      volume_id, share=None):
        """Clones mounted volume with NetApp filer."""
        (host_ip, export_path) = self._get_export_ip_path(volume_id, share)
        storage_path = self._get_actual_path_for_export(export_path)
        target_path = '%s/%s' % (storage_path, clone_name)
        (clone_id, vol_uuid) = self._start_clone('%s/%s' % (storage_path,
                                                            volume_name),
                                                 target_path)
        if vol_uuid:
            try:
                self._wait_for_clone_finish(clone_id, vol_uuid)
            except NaApiError as e:
                if e.code != 'UnknownCloneId':
                    self._clear_clone(clone_id)
                raise e

    def _get_actual_path_for_export(self, export_path):
        """Gets the actual path on the filer for export path."""
        storage_path = NaElement.create_node_with_children(
            'nfs-exportfs-storage-path', **{'pathname': export_path})
        result = self._invoke_successfully(storage_path, None)
        if result.get_child_content('actual-pathname'):
            return result.get_child_content('actual-pathname')
        raise exception.NotFound(_('No storage path found for export path %s')
                                 % (export_path))

    def _start_clone(self, src_path, dest_path):
        """Starts the clone operation.

        :returns: clone-id
        """

        msg_fmt = {'src_path': src_path, 'dest_path': dest_path}
        LOG.debug(_("""Cloning with src %(src_path)s, dest %(dest_path)s""")
                  % msg_fmt)
        clone_start = NaElement.create_node_with_children(
            'clone-start',
            **{'source-path': src_path,
                'destination-path': dest_path,
                'no-snap': 'true'})
        result = self._invoke_successfully(clone_start, None)
        clone_id_el = result.get_child_by_name('clone-id')
        cl_id_info = clone_id_el.get_child_by_name('clone-id-info')
        vol_uuid = cl_id_info.get_child_content('volume-uuid')
        clone_id = cl_id_info.get_child_content('clone-op-id')
        return (clone_id, vol_uuid)

    def _wait_for_clone_finish(self, clone_op_id, vol_uuid):
        """Waits till a clone operation is complete or errored out."""
        clone_ls_st = NaElement('clone-list-status')
        clone_id = NaElement('clone-id')
        clone_ls_st.add_child_elem(clone_id)
        clone_id.add_node_with_children('clone-id-info',
                                        **{'clone-op-id': clone_op_id,
                                            'volume-uuid': vol_uuid})
        task_running = True
        while task_running:
            result = self._invoke_successfully(clone_ls_st, None)
            status = result.get_child_by_name('status')
            ops_info = status.get_children()
            if ops_info:
                state = ops_info[0].get_child_content('clone-state')
                if state == 'completed':
                    task_running = False
                elif state == 'failed':
                    code = ops_info[0].get_child_content('error')
                    reason = ops_info[0].get_child_content('reason')
                    raise NaApiError(code, reason)
                else:
                    time.sleep(1)
            else:
                raise NaApiError(
                    'UnknownCloneId',
                    'No clone operation for clone id %s found on the filer'
                    % (clone_id))

    def _clear_clone(self, clone_id):
        """Clear the clone information.

        Invoke this in case of failed clone.
        """

        clone_clear = NaElement.create_node_with_children(
            'clone-clear',
            **{'clone-id': clone_id})
        retry = 3
        while retry:
            try:
                self._invoke_successfully(clone_clear, None)
                break
            except Exception as e:
                # Filer might be rebooting
                time.sleep(5)
            retry = retry - 1

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""
        super(NetAppDirect7modeNfsDriver, self)._update_volume_stats()
        netapp_backend = 'NetApp_NFS_7mode_direct'
        backend_name = self.configuration.safe_get('volume_backend_name')
        self._stats["volume_backend_name"] = (backend_name or
                                              'NetApp_NFS_7mode_direct')
        self._stats["vendor_name"] = 'NetApp'
        self._stats["driver_version"] = self.VERSION
        provide_ems(self, self._client, self._stats, netapp_backend,
                    server_type="7mode")

    def _shortlist_del_eligible_files(self, share, old_files):
        """Prepares list of eligible files to be deleted from cache."""
        file_list = []
        exp_volume = self._get_actual_path_for_export(share)
        for file in old_files:
            path = '/vol/%s/%s' % (exp_volume, file)
            u_bytes = self._get_filer_file_usage(path)
            file_list.append((file, u_bytes))
        LOG.debug(_('Shortlisted del elg files %s'), file_list)
        return file_list

    def _get_filer_file_usage(self, path):
        """Gets the file unique bytes."""
        LOG.debug(_('Getting file usage for %s'), path)
        file_use = NaElement.create_node_with_children(
            'file-usage-get', **{'path': path})
        res = self._invoke_successfully(file_use)
        bytes = res.get_child_content('unique-bytes')
        LOG.debug(_('file-usage for path %(path)s is %(bytes)s')
                  % {'path': path, 'bytes': bytes})
        return bytes

    def _is_filer_ip(self, ip):
        """Checks whether ip is on the same filer."""
        try:
            ifconfig = NaElement('net-ifconfig-get')
            res = self._invoke_successfully(ifconfig, None)
            if_info = res.get_child_by_name('interface-config-info')
            if if_info:
                ifs = if_info.get_children()
                for intf in ifs:
                    v4_addr = intf.get_child_by_name('v4-primary-address')
                    if v4_addr:
                        ip_info = v4_addr.get_child_by_name('ip-address-info')
                        if ip_info:
                            address = ip_info.get_child_content('address')
                            if ip == address:
                                return True
                            else:
                                continue
        except Exception:
            return False
        return False

    def _share_match_for_ip(self, ip, shares):
        """Returns the share that is served by ip.

            Multiple shares can have same dir path but
            can be served using different ips. It finds the
            share which is served by ip on same nfs server.
        """
        if self._is_filer_ip(ip) and shares:
            for share in shares:
                ip_sh = share.split(':')[0]
                if self._is_filer_ip(ip_sh):
                    LOG.debug(_('Share match found for ip %s'), ip)
                    return share
        LOG.debug(_('No share match found for ip %s'), ip)
        return None

    def _is_share_vol_compatible(self, volume, share):
        """Checks if share is compatible with volume to host it."""
        return self._is_share_eligible(share, volume['size'])
