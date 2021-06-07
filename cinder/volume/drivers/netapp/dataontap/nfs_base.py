# Copyright (c) 2012 NetApp, Inc.  All rights reserved.
# Copyright (c) 2014 Ben Swartzlander.  All rights reserved.
# Copyright (c) 2014 Navneet Singh.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Bob Callaway.  All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
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
import math
import os
import re
import threading
import time

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import netutils
from oslo_utils import units
import six
from six.moves import urllib

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import objects
import cinder.privsep.path
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.netapp.dataontap.utils import loopingcalls
from cinder.volume.drivers.netapp import options as na_opts
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume.drivers import nfs
from cinder.volume import volume_utils


LOG = logging.getLogger(__name__)
CONF = cfg.CONF
HOUSEKEEPING_INTERVAL_SECONDS = 600  # ten minutes


@six.add_metaclass(volume_utils.TraceWrapperWithABCMetaclass)
class NetAppNfsDriver(driver.ManageableVD,
                      driver.CloneableImageVD,
                      nfs.NfsDriver):
    """Base class for NetApp NFS driver for Data ONTAP."""

    # do not increment this as it may be used in volume type definitions
    VERSION = "1.0.0"

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "NetApp_CI"

    REQUIRED_FLAGS = ['netapp_login', 'netapp_password',
                      'netapp_server_hostname']
    DEFAULT_FILTER_FUNCTION = 'capabilities.utilization < 70'
    DEFAULT_GOODNESS_FUNCTION = '100 - capabilities.utilization'

    def __init__(self, *args, **kwargs):
        na_utils.validate_instantiation(**kwargs)
        self._execute = None
        self._context = None
        self.app_version = kwargs.pop("app_version", "unknown")
        kwargs['supports_auto_mosr'] = True
        super(NetAppNfsDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(na_opts.netapp_connection_opts)
        self.configuration.append_config_values(na_opts.netapp_basicauth_opts)
        self.configuration.append_config_values(na_opts.netapp_transport_opts)
        self.configuration.append_config_values(na_opts.netapp_img_cache_opts)
        self.configuration.append_config_values(na_opts.netapp_nfs_extra_opts)
        self.backend_name = self.host.split('@')[1]
        self.loopingcalls = loopingcalls.LoopingCalls()

    def do_setup(self, context):
        super(NetAppNfsDriver, self).do_setup(context)
        self._context = context
        na_utils.check_flags(self.REQUIRED_FLAGS, self.configuration)
        self.zapi_client = None

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        super(NetAppNfsDriver, self).check_for_setup_error()
        self.loopingcalls.start_tasks()

    def _add_looping_tasks(self):
        """Add tasks that need to be executed at a fixed interval.

        Inheriting class overrides and then explicitly calls this method.
        """
        # Add the task that deletes snapshots marked for deletion.
        self.loopingcalls.add_task(
            self._delete_snapshots_marked_for_deletion,
            loopingcalls.ONE_MINUTE,
            loopingcalls.ONE_MINUTE)

        # Add the task that logs EMS messages
        self.loopingcalls.add_task(
            self._handle_ems_logging,
            loopingcalls.ONE_HOUR)

    def _delete_snapshots_marked_for_deletion(self):
        snapshots = self.zapi_client.get_snapshots_marked_for_deletion()
        for snapshot in snapshots:
            self.zapi_client.delete_snapshot(
                snapshot['volume_name'], snapshot['name'])

    def _handle_ems_logging(self):
        """Log autosupport messages."""
        raise NotImplementedError()

    def get_pool(self, volume):
        """Return pool name where volume resides.

        :param volume: The volume hosted by the driver.
        :return: Name of the pool where given volume is hosted.
        """
        return volume['provider_location']

    def create_volume(self, volume):
        """Creates a volume.

        :param volume: volume reference
        """
        LOG.debug('create_volume on %s', volume['host'])
        self._ensure_flexgroup_not_in_cg(volume)
        self._ensure_shares_mounted()

        # get share as pool name
        pool_name = volume_utils.extract_host(volume['host'], level='pool')

        if pool_name is None:
            msg = _("Pool is not available in the volume host field.")
            raise exception.InvalidHost(reason=msg)

        extra_specs = na_utils.get_volume_extra_specs(volume)

        try:
            volume['provider_location'] = pool_name
            LOG.debug('Using pool %s.', pool_name)
            self._do_create_volume(volume)
            self._do_qos_for_volume(volume, extra_specs)
            model_update = self._get_volume_model_update(volume) or {}
            model_update['provider_location'] = volume['provider_location']
            return model_update
        except Exception:
            LOG.exception("Exception creating vol %(name)s on "
                          "pool %(pool)s.",
                          {'name': volume['name'],
                           'pool': volume['provider_location']})
            # We need to set this for the model update in order for the
            # manager to behave correctly.
            volume['provider_location'] = None

        msg = _("Volume %(vol)s could not be created in pool %(pool)s.")
        raise exception.VolumeBackendAPIException(data=msg % {
            'vol': volume['name'], 'pool': pool_name})

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        For a FlexGroup pool, the operation relies on the NFS generic driver
        because the ONTAP clone file is not supported by FlexGroup yet.
        """
        self._ensure_flexgroup_not_in_cg(volume)
        if (self._is_flexgroup(vol_id=snapshot['volume_id']) and
                not self._is_flexgroup_clone_file_supported()):
            model = super(NetAppNfsDriver, self).create_volume_from_snapshot(
                volume, snapshot)

            return self._do_qos_for_file_flexgroup(volume, model)
        else:
            source = {
                'name': snapshot['name'],
                'size': snapshot['volume_size'],
                'id': snapshot['volume_id'],
            }
            return self._clone_source_to_destination_volume(source, volume)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume.

        For a FlexGroup pool, the operation relies on the NFS generic driver
        because the ONTAP clone file is not supported by FlexGroup yet.
        """
        self._ensure_flexgroup_not_in_cg(volume)
        if (self._is_flexgroup(vol_id=src_vref['id']) and
                not self._is_flexgroup_clone_file_supported()):
            model = super(NetAppNfsDriver, self).create_cloned_volume(
                volume, src_vref)

            return self._do_qos_for_file_flexgroup(volume, model)
        else:
            source = {'name': src_vref['name'],
                      'size': src_vref['size'],
                      'id': src_vref['id']}
            return self._clone_source_to_destination_volume(source, volume)

    def _do_qos_for_file_flexgroup(self, volume, model):
        """Creates the QoS for a file inside the FlexGroup."""
        try:
            extra_specs = na_utils.get_volume_extra_specs(volume)
            volume['provider_location'] = model['provider_location']
            self._do_qos_for_volume(volume, extra_specs)

            model_update = (
                self._get_volume_model_update(volume) or {})
            model_update['provider_location'] = model[
                'provider_location']
            return model_update
        except Exception as e:
            LOG.exception('Exception while setting the QoS for the %(vol_id)s'
                          ' volume inside a FlexGroup pool. Exception: '
                          ' %(exc)s',
                          {'vol_id': volume['id'], 'exc': e})
            msg = _("Volume %s could not set QoS.")
            raise exception.VolumeBackendAPIException(data=msg % volume['id'])

    def _clone_source_to_destination_volume(self, source, destination_volume):
        share = self._get_volume_location(source['id'])

        extra_specs = na_utils.get_volume_extra_specs(destination_volume)

        try:
            destination_volume['provider_location'] = share
            self._clone_with_extension_check(
                source, destination_volume)
            self._do_qos_for_volume(destination_volume, extra_specs)

            model_update = (
                self._get_volume_model_update(destination_volume) or {})
            model_update['provider_location'] = destination_volume[
                'provider_location']

            return model_update
        except Exception:
            LOG.exception("Exception creating volume %(name)s from source "
                          "%(source)s on share %(share)s.",
                          {'name': destination_volume['id'],
                           'source': source['name'],
                           'share': destination_volume['provider_location']})
        msg = _("Volume %s could not be created on shares.")
        raise exception.VolumeBackendAPIException(data=msg % (
            destination_volume['id']))

    def _clone_with_extension_check(self, source, destination_volume):
        source_size = source['size']
        source_id = source['id']
        source_name = source['name']
        destination_volume_size = destination_volume['size']
        self._clone_backing_file_for_volume(source_name,
                                            destination_volume['name'],
                                            source_id)
        path = self.local_path(destination_volume)
        if self._discover_file_till_timeout(path):
            self._set_rw_permissions(path)
            if destination_volume_size != source_size:
                try:
                    self.extend_volume(destination_volume,
                                       destination_volume_size)
                except Exception:
                    LOG.error("Resizing %s failed. Cleaning "
                              "volume.", destination_volume['name'])
                    self._cleanup_volume_on_failure(destination_volume)
                    raise exception.CinderException(
                        _("Resizing clone %s failed.")
                        % destination_volume['name'])
        else:
            raise exception.CinderException(_("NFS file %s not discovered.")
                                            % destination_volume['name'])

    def _cleanup_volume_on_failure(self, volume):
        LOG.debug('Cleaning up, failed operation on %s', volume['name'])
        vol_path = self.local_path(volume)
        if os.path.exists(vol_path):
            LOG.debug('Found %s, deleting ...', vol_path)
            self._delete_file_at_path(vol_path)
        else:
            LOG.debug('Could not find  %s, continuing ...', vol_path)

    def _do_qos_for_volume(self, volume, extra_specs, cleanup=False):
        """Set QoS policy on backend from volume type information."""
        raise NotImplementedError()

    def _get_volume_model_update(self, volume):
        """Provide any updates necessary for a volume being created/managed."""
        raise NotImplementedError()

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        For a FlexGroup pool, the operation relies on the NFS generic driver
        because the ONTAP clone file is not supported by FlexGroup yet.
        """
        if (self._is_flexgroup(vol_id=snapshot['volume_id']) and
                not self._is_flexgroup_clone_file_supported()):
            self._create_snapshot_for_flexgroup(snapshot)
        else:
            self._clone_backing_file_for_volume(snapshot['volume_name'],
                                                snapshot['name'],
                                                snapshot['volume_id'],
                                                is_snapshot=True)

    def _create_snapshot_for_flexgroup(self, snapshot):
        """Creates the snapshot falling back to the Generic NFS driver.

        The generic NFS driver snapshot creates a new file which is gonna be
        the active one (used to attach). So, it must assign the QoS to this
        new file too. It does not require to create the policy group, though,
        only reusing the created one for the source volume.
        """
        try:
            super(NetAppNfsDriver, self).create_snapshot(snapshot)

            source_vol = {
                'id': snapshot['volume_id'],
                'name': snapshot['volume_name'],
                'volume_type_id': snapshot['volume_type_id'],
            }
            extra_specs = na_utils.get_volume_extra_specs(source_vol)
            qos_policy_group_is_adaptive = volume_utils.is_boolean_str(
                extra_specs.get('netapp:qos_policy_group_is_adaptive'))
            qos_policy_group_info = na_utils.get_valid_qos_policy_group_info(
                source_vol, extra_specs)
            snap_vol = {
                'name': '%s.%s' % (snapshot['volume_name'], snapshot['id']),
                'host': self._get_volume_host(source_vol['id'])
            }

            self._set_qos_policy_group_on_volume(snap_vol,
                                                 qos_policy_group_info,
                                                 qos_policy_group_is_adaptive)
        except Exception as e:
            LOG.exception('Exception while creating the %(snap_id)s snapshot'
                          ' of the %(vol_id)s volume inside a FlexGroup pool.'
                          ' Exception: %(exc)s',
                          {'snap_id': snapshot['id'],
                           'vol_id': snapshot['volume_id'],
                           'exc': e})
            msg = _("Snapshot could not be created on shares.")
            raise exception.VolumeBackendAPIException(data=msg)

    def _set_qos_policy_group_on_volume(self, volume, qos_policy_group_info,
                                        qos_policy_group_is_adaptive):
        """Set the qos policy group for a volume"""
        raise NotImplementedError()

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        if (self._is_flexgroup(vol_id=snapshot.volume_id) and
                not self._is_flexgroup_clone_file_supported()):
            super(NetAppNfsDriver, self).delete_snapshot(snapshot)
        else:
            self._delete_file(snapshot.volume_id, snapshot.name)

    def _delete_file(self, file_id, file_name):
        nfs_share = self._get_provider_location(file_id)

        if self._volume_not_present(nfs_share, file_name):
            LOG.debug('File %(file_name)s not found when attempting to delete '
                      'from share %(share)s',
                      {'file_name': file_name, 'share': nfs_share})
            return

        path = self._get_volume_path(nfs_share, file_name)
        self._delete(path)

    def _get_volume_location(self, volume_id):
        """Returns NFS mount address as <nfs_ip_address>:<nfs_mount_dir>."""
        provider_location = self._get_provider_location(volume_id)
        nfs_server_ip, export_path = na_utils.get_export_host_junction_path(
            provider_location)

        if netutils.is_valid_ipv6(nfs_server_ip):
            nfs_server_ip = netutils.escape_ipv6(nfs_server_ip)

        return nfs_server_ip + ':' + export_path

    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert a volume to a given snapshot.

        For a FlexGroup pool, the operation relies on the NFS generic driver
        because the ONTAP clone file is not supported by FlexGroup yet.
        """
        if (self._is_flexgroup(vol_id=snapshot['volume_id']) and
                not self._is_flexgroup_clone_file_supported()):
            super(NetAppNfsDriver, self).revert_to_snapshot(context, volume,
                                                            snapshot)
        else:
            self._revert_to_snapshot(volume, snapshot)

    def _clone_backing_file_for_volume(self, volume_name, clone_name,
                                       volume_id, share=None,
                                       is_snapshot=False,
                                       source_snapshot=None):
        """Clone backing file for Cinder volume."""
        raise NotImplementedError()

    def _revert_to_snapshot(self, volume, snapshot):
        raise NotImplementedError()

    def _is_flexgroup(self, vol_id=None, host=None):
        """Discover if a given volume is a FlexGroup or not"""
        raise NotImplementedError()

    def _get_backing_flexvol_names(self):
        """Returns backing flexvol names."""
        raise NotImplementedError()

    def _get_flexvol_names_from_hosts(self, hosts):
        """Returns a set of flexvol names."""
        raise NotImplementedError()

    def _get_provider_location(self, volume_id):
        """Returns provider location for given volume."""
        volume = self.db.volume_get(self._context, volume_id)
        return volume.provider_location

    def _get_volume_host(self, volume_id):
        """Returns volume host for given volume."""
        volume = self.db.volume_get(self._context, volume_id)
        return volume.host

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
                tries += 1
                if tries >= self.configuration.num_shell_tries:
                    raise
                LOG.exception("Recovering from a failed execute. "
                              "Try number %s", tries)
                time.sleep(tries ** 2)

    def _get_volume_path(self, nfs_share, volume_name):
        """Get volume path.

        Get volume path (local fs path) for given volume name on given nfs
        share.
        :param nfs_share: string, example 172.18.194.100:/var/nfs
        :param volume_name: string,
            example volume-91ee65ec-c473-4391-8c09-162b00c68a8c
        """

        return os.path.join(self._get_mount_point_for_share(nfs_share),
                            volume_name)

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""
        raise NotImplementedError()

    def get_default_filter_function(self):
        """Get the default filter_function string."""
        return self.DEFAULT_FILTER_FUNCTION

    def get_default_goodness_function(self):
        """Get the default goodness_function string."""
        return self.DEFAULT_GOODNESS_FUNCTION

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        self._ensure_flexgroup_not_in_cg(volume)
        super(NetAppNfsDriver, self).copy_image_to_volume(
            context, volume, image_service, image_id)
        LOG.info('Copied image to volume %s using regular download.',
                 volume['id'])

        if (not self._is_flexgroup(host=volume['host']) or
                self._is_flexgroup_clone_file_supported()):
            # NOTE(felipe_rodrigues): NetApp image cache relies on the
            # FlexClone file, which is only available for the earliest
            # versions of FlexGroup.
            self._register_image_in_cache(volume, image_id)

    def _register_image_in_cache(self, volume, image_id):
        """Stores image in the cache."""
        file_name = 'img-cache-%s' % image_id
        LOG.info("Registering image in cache %s", file_name)
        try:
            self._do_clone_rel_img_cache(
                volume['name'], file_name,
                volume['provider_location'], file_name)
        except Exception as e:
            LOG.warning('Exception while registering image %(image_id)s'
                        ' in cache. Exception: %(exc)s',
                        {'image_id': image_id, 'exc': e})

    def _find_image_in_cache(self, image_id):
        """Finds image in cache and returns list of shares with file name."""
        result = []
        if getattr(self, '_mounted_shares', None):
            for share in self._mounted_shares:
                dir = self._get_mount_point_for_share(share)
                file_name = 'img-cache-%s' % image_id
                file_path = '%s/%s' % (dir, file_name)
                if os.path.isfile(file_path):
                    LOG.debug('Found cache file for image %(image_id)s'
                              ' on share %(share)s',
                              {'image_id': image_id, 'share': share})
                    result.append((share, file_name))
        return result

    def _do_clone_rel_img_cache(self, src, dst, share, cache_file):
        """Do clone operation w.r.t image cache file."""
        @utils.synchronized(cache_file, external=True)
        def _do_clone():
            dir = self._get_mount_point_for_share(share)
            file_path = '%s/%s' % (dir, dst)
            if not os.path.exists(file_path):
                LOG.info('Cloning from cache to destination %s', dst)
                self._clone_backing_file_for_volume(src, dst, volume_id=None,
                                                    share=share)
                src_path = '%s/%s' % (dir, src)
                os.utime(src_path, None)
        _do_clone()

    @utils.synchronized('clean_cache')
    def _spawn_clean_cache_job(self):
        """Spawns a clean task if not running."""
        if getattr(self, 'cleaning', None):
            LOG.debug('Image cache cleaning in progress. Returning... ')
            return
        else:
            # Set cleaning to True
            self.cleaning = True
            t = threading.Timer(0, self._clean_image_cache)
            t.start()

    def _clean_image_cache(self):
        """Clean the image cache files in cache of space crunch."""
        try:
            LOG.debug('Image cache cleaning in progress.')
            thres_size_perc_start = (
                self.configuration.thres_avl_size_perc_start)
            thres_size_perc_stop = self.configuration.thres_avl_size_perc_stop
            for share in getattr(self, '_mounted_shares', []):
                try:
                    total_size, total_avl = self._get_capacity_info(share)
                    avl_percent = int((float(total_avl) / total_size) * 100)
                    if avl_percent <= thres_size_perc_start:
                        LOG.info('Cleaning cache for share %s.', share)
                        eligible_files = self._find_old_cache_files(share)
                        threshold_size = int(
                            (thres_size_perc_stop * total_size) / 100)
                        bytes_to_free = int(threshold_size - total_avl)
                        LOG.debug('Files to be queued for deletion %s',
                                  eligible_files)
                        self._delete_files_till_bytes_free(
                            eligible_files, share, bytes_to_free)
                    else:
                        continue
                except Exception as e:
                    LOG.warning('Exception during cache cleaning'
                                ' %(share)s. Message - %(ex)s',
                                {'share': share, 'ex': e})
                    continue
        finally:
            LOG.debug('Image cache cleaning done.')
            self.cleaning = False

    def _shortlist_del_eligible_files(self, share, old_files):
        """Prepares list of eligible files to be deleted from cache."""
        raise NotImplementedError()

    def _find_old_cache_files(self, share):
        """Finds the old files in cache."""
        mount_fs = self._get_mount_point_for_share(share)
        threshold_minutes = self.configuration.expiry_thres_minutes
        cmd = ['find', mount_fs, '-maxdepth', '1', '-name',
               'img-cache*', '-amin', '+%s' % threshold_minutes]
        res, _err = self._execute(*cmd, run_as_root=self._execute_as_root)
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
        LOG.debug('Bytes to free %s', bytes_to_free)
        if file_list and bytes_to_free > 0:
            sorted_files = sorted(file_list, key=lambda x: x[1], reverse=True)
            mount_fs = self._get_mount_point_for_share(share)
            for f in sorted_files:
                if f:
                    file_path = '%s/%s' % (mount_fs, f[0])
                    LOG.debug('Delete file path %s', file_path)

                    @utils.synchronized(f[0], external=True)
                    def _do_delete():
                        if self._delete_file_at_path(file_path):
                            return True
                        return False

                    if _do_delete():
                        bytes_to_free -= int(f[1])
                        if bytes_to_free <= 0:
                            return

    def _delete_file_at_path(self, path):
        """Delete file from disk and return result as boolean."""
        try:
            LOG.debug('Deleting file at path %s', path)
            cmd = ['rm', '-f', path]
            self._execute(*cmd, run_as_root=self._execute_as_root)
            return True
        except Exception as ex:
            LOG.warning('Exception during deleting %s', ex)
            return False

    def _copy_from_cache(self, volume, image_id, cache_result):
        """Try copying image file_name from cached file"""
        raise NotImplementedError()

    def _copy_from_img_service(self, context, volume, image_service,
                               image_id):
        raise NotImplementedError()

    def clone_image(self, context, volume,
                    image_location, image_meta,
                    image_service):
        """Create a volume efficiently from an existing image.

        image_location is a string whose format depends on the
        image service backend in use. The driver should use it
        to determine whether cloning is possible.

        Returns a dict of volume properties eg. provider_location,
        boolean indicating whether cloning occurred.
        """
        if (self._is_flexgroup(host=volume['host']) and
                not self._is_flexgroup_clone_file_supported()):
            return None, False

        image_id = image_meta['id']
        cloned = False
        post_clone = False

        extra_specs = na_utils.get_volume_extra_specs(volume)
        major, minor = self.zapi_client.get_ontapi_version()
        col_path = self.configuration.netapp_copyoffload_tool_path

        try:
            cache_result = self._find_image_in_cache(image_id)
            if cache_result:
                cloned = self._copy_from_cache(volume, image_id, cache_result)
            else:
                cloned = self._direct_nfs_clone(volume, image_location,
                                                image_id)

            # Try to use the copy offload tool
            if not cloned and col_path and major == 1 and minor >= 20:
                cloned = self._copy_from_img_service(context, volume,
                                                     image_service, image_id)

            if cloned:
                self._do_qos_for_volume(volume, extra_specs)
                post_clone = self._post_clone_image(volume)
        except Exception as e:
            msg = e.msg if getattr(e, 'msg', None) else e
            LOG.info('Image cloning unsuccessful for image'
                     ' %(image_id)s. Message: %(msg)s',
                     {'image_id': image_id, 'msg': msg})
        finally:
            cloned = cloned and post_clone
            share = (volume_utils.extract_host(volume['host'], level='pool')
                     if cloned else None)
            bootable = True if cloned else False
            return {'provider_location': share, 'bootable': bootable}, cloned

    def _clone_from_cache(self, volume, image_id, cache_result):
        """Clones a copy from image cache."""
        cloned = False
        LOG.info('Cloning image %s from cache', image_id)
        path = volume.host.split('#')[1]
        for res in cache_result:
            # Repeat tries in other shares if failed in some
            (share, file_name) = res
            if path == share:
                LOG.debug('Cache share: %s', share)
                if (share and
                        self._is_share_clone_compatible(volume, share)):
                    try:
                        self._do_clone_rel_img_cache(
                            file_name, volume['name'], share, file_name)
                        cloned = True
                        volume['provider_location'] = share
                        break
                    except Exception:
                        LOG.warning('Unexpected exception during'
                                    ' image cloning in share %s', share)
        return cloned

    def _direct_nfs_clone(self, volume, image_location, image_id):
        """Clone directly in nfs share."""
        LOG.info('Checking image clone %s from glance share.', image_id)
        cloned = False
        image_locations = self._construct_image_nfs_url(image_location)
        run_as_root = self._execute_as_root
        for loc in image_locations:
            share = self._is_cloneable_share(loc)
            if share and self._is_share_clone_compatible(volume, share):
                LOG.debug('Share is cloneable %s', share)
                (__, ___, img_file) = loc.rpartition('/')
                dir_path = self._get_mount_point_for_share(share)
                img_path = '%s/%s' % (dir_path, img_file)
                img_info = image_utils.qemu_img_info(img_path,
                                                     run_as_root=run_as_root)
                if img_info.file_format == 'raw':
                    LOG.debug('Image is raw %s', image_id)
                    self._clone_backing_file_for_volume(
                        img_file, volume['name'],
                        volume_id=None, share=share)
                    cloned = True
                    break
                else:
                    LOG.info(
                        'Image will locally be converted to raw %s',
                        image_id)
                    dst = '%s/%s' % (dir_path, volume['name'])
                    image_utils.convert_image(img_path, dst, 'raw',
                                              run_as_root=run_as_root)
                    data = image_utils.qemu_img_info(dst,
                                                     run_as_root=run_as_root)
                    if data.file_format != "raw":
                        raise exception.InvalidResults(
                            _("Converted to raw, but"
                              " format is now %s") % data.file_format)
                    else:
                        cloned = True
                        self._register_image_in_cache(
                            volume, image_id)
                        break
        return cloned

    def _post_clone_image(self, volume):
        """Do operations post image cloning."""
        LOG.info('Performing post clone for %s', volume['name'])

        share = volume_utils.extract_host(volume['host'], level='pool')
        vol_path = self._get_volume_path(share, volume['name'])

        if self._discover_file_till_timeout(vol_path):
            self._set_rw_permissions(vol_path)
            self._resize_image_file(vol_path, volume['size'])
            return True
        raise exception.InvalidResults(
            _("NFS file could not be discovered."))

    def _resize_image_file(self, path, new_size, file_format=None):
        """Resize the image file on share to new size."""
        LOG.debug('Checking file for resize')
        if self._is_file_size_equal(path, new_size):
            return
        else:
            LOG.info('Resizing file to %sG', new_size)
            image_utils.resize_image(path, new_size,
                                     run_as_root=self._execute_as_root,
                                     file_format=file_format)
            if file_format == 'qcow2' and not self._is_file_size_equal(
                    path, new_size):
                raise exception.InvalidResults(
                    _('Resizing image file failed.'))

    def _is_file_size_equal(self, path, size):
        """Checks if file size at path is equal to size."""
        data = image_utils.qemu_img_info(path,
                                         run_as_root=self._execute_as_root)
        virt_size = data.virtual_size / units.Gi
        if virt_size == size:
            return True
        else:
            return False

    def _touch_path_to_refresh(self, path):
        # Touching parent directory forces NFS client to flush its cache.
        cinder.privsep.path.touch(path)

    def _discover_file_till_timeout(self, path, timeout=75):
        """Checks if file size at path is equal to size."""
        # Sometimes nfs takes time to discover file
        # Retrying in case any unexpected situation occurs
        #
        # The NFS client by default has a 60 second maximum
        # cache time before it refreshes directory information.
        # (See man 5 nfs acdirmax.)  Allow 75 seconds for
        # retries to ensure that this cache has refreshed.
        retry_seconds = timeout
        sleep_interval = 2
        base_path = os.path.dirname(path)
        self._touch_path_to_refresh(base_path)

        while True:
            if os.path.exists(path):
                return True
            else:
                if retry_seconds <= 0:
                    LOG.warning('Discover file retries exhausted.')
                    return False
                else:
                    time.sleep(sleep_interval)
                    retry_seconds -= sleep_interval
                    self._touch_path_to_refresh(base_path)

    def _is_cloneable_share(self, image_location):
        """Finds if the image at location is cloneable."""
        conn, dr = self._check_get_nfs_path_segs(image_location)
        return self._check_share_in_use(conn, dr)

    def _check_get_nfs_path_segs(self, image_location):
        """Checks if the nfs path format is matched.

            WebNFS url format with relative-path is supported.
            Accepting all characters in path-names and checking
            against the mounted shares which will contain only
            allowed path segments. Returns connection and dir details.
        """
        conn, dr = None, None
        if image_location:
            nfs_loc_pattern = \
                (r'^nfs://(([\w\-\.]+:{1}[\d]+|[\w\-\.]+)(/[^\/].*)'
                 r'*(/[^\/\\\\]+)$)')
            matched = re.match(nfs_loc_pattern, image_location, flags=0)
            if not matched:
                LOG.debug('Image location not in the'
                          ' expected format %s', image_location)
            else:
                conn = matched.group(2)
                dr = matched.group(3) or '/'
        return conn, dr

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
                ip = volume_utils.resolve_hostname(host)
                share_candidates = []
                for sh in self._mounted_shares:
                    sh_exp = sh.split(':')[-1]
                    if sh_exp == dir:
                        share_candidates.append(sh)
                if share_candidates:
                    LOG.debug('Found possible share matches %s',
                              share_candidates)
                    return self._share_match_for_ip(ip, share_candidates)
        except Exception:
            LOG.warning("Unexpected exception while "
                        "short listing used share.")
        return None

    def _construct_image_nfs_url(self, image_location):
        """Construct direct url for nfs backend.

             It creates direct url from image_location
             which is a tuple with direct_url and locations.
             Returns array of urls with nfs scheme if nfs store
             else returns url. It needs to be verified
             by backend before use.
        """

        direct_url, locations = image_location
        if not direct_url and not locations:
            raise exception.NotFound(_('Image location not present.'))

        urls = []
        if not locations:
            urls.append(direct_url)
        else:
            for location in locations:
                if not location['metadata']:
                    continue
                location_type = location['metadata'].get('type')
                if not location_type or location_type.lower() != "nfs":
                    continue
                share_location = location['metadata'].get('share_location')
                mountpoint = location['metadata'].get('mountpoint')
                if not share_location or not mountpoint:
                    continue
                url = location['url']
                url_parse = urllib.parse.urlparse(url)
                abs_path = os.path.join(url_parse.netloc, url_parse.path)
                rel_path = os.path.relpath(abs_path, mountpoint)
                direct_url = "%s/%s" % (share_location, rel_path)
                urls.append(direct_url)
        return urls

    def extend_volume(self, volume, new_size):
        """Extend an existing volume to the new size."""

        LOG.info('Extending volume %s.', volume['name'])

        try:
            path = self.local_path(volume)
            file_format = None
            admin_metadata = objects.Volume.get_by_id(
                context.get_admin_context(), volume.id).admin_metadata
            if admin_metadata and 'format' in admin_metadata:
                file_format = admin_metadata['format']
            self._resize_image_file(
                path, new_size, file_format=file_format)
        except Exception as err:
            exception_msg = (_("Failed to extend volume "
                               "%(name)s, Error msg: %(msg)s.") %
                             {'name': volume['name'],
                              'msg': six.text_type(err)})
            raise exception.VolumeBackendAPIException(data=exception_msg)

        try:
            extra_specs = na_utils.get_volume_extra_specs(volume)

            # Create volume copy with new size for size-dependent QOS specs
            volume_copy = copy.copy(volume)
            volume_copy['size'] = new_size

            self._do_qos_for_volume(volume_copy, extra_specs, cleanup=False)
        except Exception as err:
            exception_msg = (_("Failed to set QoS for existing volume "
                               "%(name)s, Error msg: %(msg)s.") %
                             {'name': volume['name'],
                              'msg': six.text_type(err)})
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def _is_share_clone_compatible(self, volume, share):
        """Checks if share is compatible with volume to host its clone."""
        raise NotImplementedError()

    def _check_share_can_hold_size(self, share, size):
        """Checks if volume can hold image with size."""
        _tot_size, tot_available = self._get_capacity_info(
            share)
        if tot_available < size:
            msg = _("Container size smaller than required file size.")
            raise exception.VolumeDriverException(msg)

    def _move_nfs_file(self, source_path, dest_path):
        """Moves source to destination."""

        @utils.synchronized(dest_path, external=True)
        def _move_file(src, dst):
            if os.path.exists(dst):
                LOG.warning("Destination %s already exists.", dst)
                return False
            self._execute('mv', src, dst, run_as_root=self._execute_as_root)
            return True

        try:
            return _move_file(source_path, dest_path)
        except Exception as e:
            LOG.warning('Exception moving file %(src)s. Message - %(e)s',
                        {'src': source_path, 'e': e})
        return False

    def _get_export_ip_path(self, volume_id=None, share=None):
        """Returns export ip and path.

          One of volume id or share is used to return the values.
        """

        if volume_id:
            provider_location = self._get_provider_location(volume_id)
            host_ip, export_path = na_utils.get_export_host_junction_path(
                provider_location)
        elif share:
            host_ip, export_path = na_utils.get_export_host_junction_path(
                share)
        else:
            raise exception.InvalidInput(
                'A volume ID or share was not specified.')
        return host_ip, export_path

    def _get_share_capacity_info(self, nfs_share):
        """Returns the share capacity metrics needed by the scheduler."""

        capacity = dict()
        capacity['reserved_percentage'] = self.reserved_percentage
        capacity['max_over_subscription_ratio'] = (
            self.max_over_subscription_ratio)
        total_size, total_available = self._get_capacity_info(nfs_share)
        capacity['total_capacity_gb'] = na_utils.round_down(
            total_size / units.Gi)
        capacity['free_capacity_gb'] = na_utils.round_down(
            total_available / units.Gi)

        return capacity

    def _get_capacity_info(self, nfs_share):
        """Get total capacity and free capacity in bytes for an nfs share."""
        export_path = nfs_share.rsplit(':', 1)[1]
        capacity = self.zapi_client.get_flexvol_capacity(
            flexvol_path=export_path)
        return capacity['size-total'], capacity['size-available']

    def _check_volume_type(self, volume, share, file_name, extra_specs):
        """Match volume type for share file."""

    def _convert_vol_ref_share_name_to_share_ip(self, vol_ref):
        """Converts the share point name to an IP address

        The volume reference may have a DNS name portion in the share name.
        Convert that to an IP address and then restore the entire path.

        :param vol_ref:  Driver-specific information used to identify a volume
        :return:         A volume reference where share is in IP format.
        """
        # First strip out share and convert to IP format.
        share_split = vol_ref.rsplit(':', 1)

        vol_ref_share_ip = volume_utils.resolve_hostname(share_split[0])

        # Now place back into volume reference.
        vol_ref_share = vol_ref_share_ip + ':' + share_split[1]

        return vol_ref_share

    def _get_share_mount_and_vol_from_vol_ref(self, vol_ref):
        """Get the NFS share, the NFS mount, and the volume from reference

        Determine the NFS share point, the NFS mount point, and the volume
        (with possible path) from the given volume reference. Raise exception
        if unsuccessful.

        :param vol_ref: Driver-specific information used to identify a volume
        :return:        NFS Share, NFS mount, volume path or raise error
        """
        # Check that the reference is valid.
        if 'source-name' not in vol_ref:
            reason = _('Reference must contain source-name element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=vol_ref, reason=reason)
        vol_ref_name = vol_ref['source-name']

        self._ensure_shares_mounted()

        # If a share was declared as '1.2.3.4:/a/b/c' in the nfs_shares_config
        # file, but the admin tries to manage the file located at
        # 'my.hostname.com:/a/b/c/d.vol', this might cause a lookup miss below
        # when searching self._mounted_shares to see if we have an existing
        # mount that would work to access the volume-to-be-managed (a string
        # comparison is done instead of IP comparison).
        vol_ref_share = self._convert_vol_ref_share_name_to_share_ip(
            vol_ref_name)
        for nfs_share in self._mounted_shares:
            cfg_share = self._convert_vol_ref_share_name_to_share_ip(nfs_share)
            (orig_share, work_share, file_path) = \
                vol_ref_share.partition(cfg_share)
            if work_share == cfg_share:
                file_path = file_path[1:]  # strip off leading path divider
                LOG.debug("Found possible share %s; checking mount.",
                          work_share)
                nfs_mount = self._get_mount_point_for_share(nfs_share)
                vol_full_path = os.path.join(nfs_mount, file_path)
                if os.path.isfile(vol_full_path):
                    LOG.debug("Found share %(share)s and vol %(path)s on "
                              "mount %(mnt)s",
                              {'share': nfs_share, 'path': file_path,
                               'mnt': nfs_mount})
                    return nfs_share, nfs_mount, file_path
            else:
                LOG.debug("vol_ref %(ref)s not on share %(share)s.",
                          {'ref': vol_ref_share, 'share': nfs_share})

        raise exception.ManageExistingInvalidReference(
            existing_ref=vol_ref,
            reason=_('Volume not found on configured storage backend.'))

    def manage_existing(self, volume, existing_vol_ref):
        """Manages an existing volume.

        The specified Cinder volume is to be taken into Cinder management.
        The driver will verify its existence and then rename it to the
        new Cinder volume name. It is expected that the existing volume
        reference is an NFS share point and some [/path]/volume;
        e.g., 10.10.32.1:/openstack/vol_to_manage
        or 10.10.32.1:/openstack/some_directory/vol_to_manage

        :param volume:           Cinder volume to manage
        :param existing_vol_ref: Driver-specific information used to identify a
                                 volume
        """
        # Attempt to find NFS share, NFS mount, and volume path from vol_ref.
        (nfs_share, nfs_mount, vol_path) = \
            self._get_share_mount_and_vol_from_vol_ref(existing_vol_ref)

        LOG.debug("Asked to manage NFS volume %(vol)s, with vol ref %(ref)s",
                  {'vol': volume['id'],
                   'ref': existing_vol_ref['source-name']})

        extra_specs = na_utils.get_volume_extra_specs(volume)

        self._check_volume_type(volume, nfs_share, vol_path, extra_specs)

        if vol_path == volume['name']:
            LOG.debug("New Cinder volume %s name matches reference name: "
                      "no need to rename.", volume['name'])
        else:
            src_vol = os.path.join(nfs_mount, vol_path)
            dst_vol = os.path.join(nfs_mount, volume['name'])
            try:
                self._execute("mv", src_vol, dst_vol,
                              run_as_root=self._execute_as_root,
                              check_exit_code=True)
                LOG.debug("Setting newly managed Cinder volume name to %s",
                          volume['name'])
                self._set_rw_permissions_for_all(dst_vol)
            except processutils.ProcessExecutionError as err:
                exception_msg = (_("Failed to manage existing volume %(name)s,"
                                   " because rename operation failed:"
                                   " Error msg: %(msg)s."),
                                 {'name': existing_vol_ref['source-name'],
                                  'msg': err})
                raise exception.VolumeBackendAPIException(data=exception_msg)
        try:
            self._do_qos_for_volume(volume, extra_specs, cleanup=False)
        except Exception as err:
            exception_msg = (_("Failed to set QoS for existing volume "
                               "%(name)s, Error msg: %(msg)s.") %
                             {'name': existing_vol_ref['source-name'],
                              'msg': six.text_type(err)})
            raise exception.VolumeBackendAPIException(data=exception_msg)

        model_update = self._get_volume_model_update(volume) or {}
        model_update['provider_location'] = nfs_share

        return model_update

    def manage_existing_get_size(self, volume, existing_vol_ref):
        """Returns the size of volume to be managed by manage_existing.

        When calculating the size, round up to the next GB.

        :param volume:           Cinder volume to manage
        :param existing_vol_ref: Existing volume to take under management
        """
        # Attempt to find NFS share, NFS mount, and volume path from vol_ref.
        (nfs_share, nfs_mount, vol_path) = \
            self._get_share_mount_and_vol_from_vol_ref(existing_vol_ref)

        try:
            LOG.debug("Asked to get size of NFS vol_ref %s.",
                      existing_vol_ref['source-name'])

            file_path = os.path.join(nfs_mount, vol_path)
            file_size = float(utils.get_file_size(file_path)) / units.Gi
            vol_size = int(math.ceil(file_size))
        except (OSError, ValueError):
            exception_message = (_("Failed to manage existing volume "
                                   "%(name)s, because of error in getting "
                                   "volume size."),
                                 {'name': existing_vol_ref['source-name']})
            raise exception.VolumeBackendAPIException(data=exception_message)

        LOG.debug("Reporting size of NFS volume ref %(ref)s as %(size)d GB.",
                  {'ref': existing_vol_ref['source-name'], 'size': vol_size})

        return vol_size

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

           Does not delete the underlying backend storage object. A log entry
           will be made to notify the Admin that the volume is no longer being
           managed.

           :param volume: Cinder volume to unmanage
        """
        vol_str = CONF.volume_name_template % volume['id']
        vol_path = os.path.join(volume['provider_location'], vol_str)
        LOG.info('Cinder NFS volume with current path "%(cr)s" is '
                 'no longer being managed.', {'cr': vol_path})

    def _find_share(self, volume):
        """Returns the NFS share for the created volume.

        The method is used by base class to determine the
        provider_location share of the new volume.

        :param volume: the volume to be created.
        """
        pool_name = volume_utils.extract_host(volume['host'], level='pool')

        if pool_name is None:
            msg = _("Pool is not available in the volume host field.")
            raise exception.InvalidHost(reason=msg)

        return pool_name

    def _ensure_flexgroup_not_in_cg(self, volume):
        if (self._is_flexgroup(host=volume['host']) and volume['group'] and
                volume_utils.is_group_a_cg_snapshot_type(volume['group'])):
            msg = _("Cannot create %s volume on FlexGroup pool with "
                    "consistency group.")
            raise na_utils.NetAppDriverException(msg % volume['id'])

    def _is_flexgroup_clone_file_supported(self):
        """Check whether storage can perform clone file for FlexGroup"""
        raise NotImplementedError()

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        # Implemented to prevent NFSDriver's implementation renaming the file
        # and breaking volume's backend QoS.
        msg = _("The method update_migrated_volume is not implemented.")
        raise NotImplementedError(msg)
