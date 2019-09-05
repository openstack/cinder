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

import os
import uuid

from oslo_log import log as logging
from oslo_utils import excutils
import six

from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder.objects import fields
from cinder import utils
from cinder.volume.drivers.netapp.dataontap import nfs_base
from cinder.volume.drivers.netapp.dataontap.performance import perf_cmode
from cinder.volume.drivers.netapp.dataontap.utils import capabilities
from cinder.volume.drivers.netapp.dataontap.utils import data_motion
from cinder.volume.drivers.netapp.dataontap.utils import loopingcalls
from cinder.volume.drivers.netapp.dataontap.utils import utils as dot_utils
from cinder.volume.drivers.netapp import options as na_opts
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)


@interface.volumedriver
@six.add_metaclass(utils.TraceWrapperWithABCMetaclass)
class NetAppCmodeNfsDriver(nfs_base.NetAppNfsDriver,
                           data_motion.DataMotionMixin):
    """NetApp NFS driver for Data ONTAP (Cluster-mode)."""

    REQUIRED_CMODE_FLAGS = ['netapp_vserver']

    def __init__(self, *args, **kwargs):
        super(NetAppCmodeNfsDriver, self).__init__(*args, **kwargs)
        self.driver_name = 'NetApp_NFS_Cluster_direct'
        self.driver_mode = 'cluster'
        self.configuration.append_config_values(na_opts.netapp_cluster_opts)
        self.failed_over_backend_name = kwargs.get('active_backend_id')
        self.failed_over = self.failed_over_backend_name is not None
        self.replication_enabled = (
            True if self.get_replication_backend_names(
                self.configuration) else False)

    def do_setup(self, context):
        """Do the customized set up on client for cluster mode."""
        super(NetAppCmodeNfsDriver, self).do_setup(context)
        na_utils.check_flags(self.REQUIRED_CMODE_FLAGS, self.configuration)

        # cDOT API client
        self.zapi_client = dot_utils.get_client_for_backend(
            self.failed_over_backend_name or self.backend_name)
        self.vserver = self.zapi_client.vserver

        # Storage service catalog
        self.ssc_library = capabilities.CapabilitiesLibrary(
            'nfs', self.vserver, self.zapi_client, self.configuration)

        self.ssc_library.check_api_permissions()
        self.using_cluster_credentials = (
            self.ssc_library.cluster_user_supported())

        # Performance monitoring library
        self.perf_library = perf_cmode.PerformanceCmodeLibrary(
            self.zapi_client)

    def _update_zapi_client(self, backend_name):
        """Set cDOT API client for the specified config backend stanza name."""

        self.zapi_client = dot_utils.get_client_for_backend(backend_name)
        self.vserver = self.zapi_client.vserver
        self.ssc_library._update_for_failover(self.zapi_client,
                                              self._get_flexvol_to_pool_map())
        ssc = self.ssc_library.get_ssc()
        self.perf_library._update_for_failover(self.zapi_client, ssc)

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate."""
        self._add_looping_tasks()
        super(NetAppCmodeNfsDriver, self).check_for_setup_error()

    def _add_looping_tasks(self):
        """Add tasks that need to be executed at a fixed interval."""

        # Note(cknight): Run the update once in the current thread to prevent a
        # race with the first invocation of _update_volume_stats.
        self._update_ssc()

        # Add the task that updates the slow-changing storage service catalog
        self.loopingcalls.add_task(self._update_ssc,
                                   loopingcalls.ONE_HOUR,
                                   loopingcalls.ONE_HOUR)

        # Add the task that runs other housekeeping tasks, such as deletion
        # of previously soft-deleted storage artifacts.
        self.loopingcalls.add_task(
            self._handle_housekeeping_tasks,
            loopingcalls.TEN_MINUTES,
            0)

        super(NetAppCmodeNfsDriver, self)._add_looping_tasks()

    def _handle_ems_logging(self):
        """Log autosupport messages."""

        base_ems_message = dot_utils.build_ems_log_message_0(
            self.driver_name, self.app_version)
        self.zapi_client.send_ems_log_message(base_ems_message)

        pool_ems_message = dot_utils.build_ems_log_message_1(
            self.driver_name, self.app_version, self.vserver,
            self._get_backing_flexvol_names(), [])
        self.zapi_client.send_ems_log_message(pool_ems_message)

    def _handle_housekeeping_tasks(self):
        """Handle various cleanup activities."""
        active_backend = self.failed_over_backend_name or self.backend_name

        # Add the task that harvests soft-deleted QoS policy groups.
        if self.using_cluster_credentials:
            self.zapi_client.remove_unused_qos_policy_groups()

        LOG.debug("Current service state: Replication enabled: %("
                  "replication)s. Failed-Over: %(failed)s. Active Backend "
                  "ID: %(active)s",
                  {
                      'replication': self.replication_enabled,
                      'failed': self.failed_over,
                      'active': active_backend,
                  })

        # Create pool mirrors if whole-backend replication configured
        if self.replication_enabled and not self.failed_over:
            self.ensure_snapmirrors(
                self.configuration, self.backend_name,
                self.ssc_library.get_ssc_flexvol_names())

    def _do_qos_for_volume(self, volume, extra_specs, cleanup=True):
        try:
            qos_policy_group_info = na_utils.get_valid_qos_policy_group_info(
                volume, extra_specs)
            self.zapi_client.provision_qos_policy_group(qos_policy_group_info)
            self._set_qos_policy_group_on_volume(volume, qos_policy_group_info)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Setting QoS for %s failed", volume['id'])
                if cleanup:
                    LOG.debug("Cleaning volume %s", volume['id'])
                    self._cleanup_volume_on_failure(volume)

    def _get_volume_model_update(self, volume):
        """Provide model updates for a volume being created."""
        if self.replication_enabled:
            return {'replication_status': fields.ReplicationStatus.ENABLED}

    def _set_qos_policy_group_on_volume(self, volume, qos_policy_group_info):
        if qos_policy_group_info is None:
            return
        qos_policy_group_name = na_utils.get_qos_policy_group_name_from_info(
            qos_policy_group_info)
        if qos_policy_group_name is None:
            return
        target_path = '%s' % (volume['name'])
        share = volume_utils.extract_host(volume['host'], level='pool')
        __, export_path = na_utils.get_export_host_junction_path(share)
        flex_vol_name = self.zapi_client.get_vol_by_junc_vserver(self.vserver,
                                                                 export_path)
        self.zapi_client.file_assign_qos(flex_vol_name,
                                         qos_policy_group_name,
                                         target_path)

    def _clone_backing_file_for_volume(self, volume_name, clone_name,
                                       volume_id, share=None,
                                       is_snapshot=False,
                                       source_snapshot=None):
        """Clone backing file for Cinder volume."""
        (vserver, exp_volume) = self._get_vserver_and_exp_vol(volume_id, share)
        self.zapi_client.clone_file(exp_volume, volume_name, clone_name,
                                    vserver, is_snapshot=is_snapshot)

    def _get_vserver_and_exp_vol(self, volume_id=None, share=None):
        """Gets the vserver and export volume for share."""
        (host_ip, export_path) = self._get_export_ip_path(volume_id, share)
        ifs = self.zapi_client.get_if_info_by_ip(host_ip)
        vserver = ifs[0].get_child_content('vserver')
        exp_volume = self.zapi_client.get_vol_by_junc_vserver(vserver,
                                                              export_path)
        return vserver, exp_volume

    def _update_volume_stats(self):
        """Retrieve stats info from vserver."""

        LOG.debug('Updating volume stats')
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.driver_name
        data['vendor_name'] = 'NetApp'
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = 'nfs'
        data['pools'] = self._get_pool_stats(
            filter_function=self.get_filter_function(),
            goodness_function=self.get_goodness_function())
        data['sparse_copy_volume'] = True

        # Used for service state report
        data['replication_enabled'] = self.replication_enabled

        self._spawn_clean_cache_job()
        self._stats = data

    def _get_pool_stats(self, filter_function=None, goodness_function=None):
        """Retrieve pool (Data ONTAP flexvol) stats.

        Pool statistics are assembled from static driver capabilities, the
        Storage Service Catalog of flexvol attributes, and real-time capacity
        and controller utilization metrics.  The pool name is the NFS share
        path.
        """

        pools = []

        ssc = self.ssc_library.get_ssc()
        if not ssc:
            return pools

        # Utilization and performance metrics require cluster-scoped
        # credentials
        if self.using_cluster_credentials:
            # Get up-to-date node utilization metrics just once
            self.perf_library.update_performance_cache(ssc)

            # Get up-to-date aggregate capacities just once
            aggregates = self.ssc_library.get_ssc_aggregates()
            aggr_capacities = self.zapi_client.get_aggregate_capacities(
                aggregates)
        else:
            aggr_capacities = {}

        for ssc_vol_name, ssc_vol_info in ssc.items():

            pool = dict()

            # Add storage service catalog data
            pool.update(ssc_vol_info)

            # Add driver capabilities and config info
            pool['QoS_support'] = self.using_cluster_credentials
            pool['consistencygroup_support'] = True
            pool['consistent_group_snapshot_enabled'] = True
            pool['multiattach'] = True
            pool['online_extend_support'] = False

            # Add up-to-date capacity info
            nfs_share = ssc_vol_info['pool_name']
            capacity = self._get_share_capacity_info(nfs_share)
            pool.update(capacity)

            if self.using_cluster_credentials:
                dedupe_used = self.zapi_client.get_flexvol_dedupe_used_percent(
                    ssc_vol_name)
            else:
                dedupe_used = 0.0
            pool['netapp_dedupe_used_percent'] = na_utils.round_down(
                dedupe_used)

            aggregate_name = ssc_vol_info.get('netapp_aggregate')
            aggr_capacity = aggr_capacities.get(aggregate_name, {})
            pool['netapp_aggregate_used_percent'] = aggr_capacity.get(
                'percent-used', 0)

            # Add utilization data
            utilization = self.perf_library.get_node_utilization_for_pool(
                ssc_vol_name)
            pool['utilization'] = na_utils.round_down(utilization)
            pool['filter_function'] = filter_function
            pool['goodness_function'] = goodness_function

            # Add replication capabilities/stats
            pool.update(
                self.get_replication_backend_stats(self.configuration))

            pools.append(pool)

        return pools

    def _update_ssc(self):
        """Refresh the storage service catalog with the latest set of pools."""

        self._ensure_shares_mounted()
        self.ssc_library.update_ssc(self._get_flexvol_to_pool_map())

    def _get_flexvol_to_pool_map(self):
        """Get the flexvols that back all mounted shares.

        The map is of the format suitable for seeding the storage service
        catalog: {<flexvol_name> : {'pool_name': <share_path>}}
        """

        pools = {}
        vserver_addresses = self.zapi_client.get_operational_lif_addresses()

        for share in self._mounted_shares:
            host, junction_path = na_utils.get_export_host_junction_path(share)

            address = utils.resolve_hostname(host)

            if address not in vserver_addresses:
                LOG.warning('Address not found for NFS share %s.', share)
                continue

            try:
                flexvol = self.zapi_client.get_flexvol(
                    flexvol_path=junction_path)
                pools[flexvol['name']] = {'pool_name': share}
            except exception.VolumeBackendAPIException:
                LOG.exception('Flexvol not found for NFS share %s.', share)

        return pools

    def _shortlist_del_eligible_files(self, share, old_files):
        """Prepares list of eligible files to be deleted from cache."""
        file_list = []
        (vserver, exp_volume) = self._get_vserver_and_exp_vol(
            volume_id=None, share=share)
        for old_file in old_files:
            path = '/vol/%s/%s' % (exp_volume, old_file)
            u_bytes = self.zapi_client.get_file_usage(path, vserver)
            file_list.append((old_file, u_bytes))
        LOG.debug('Shortlisted files eligible for deletion: %s', file_list)
        return file_list

    def _share_match_for_ip(self, ip, shares):
        """Returns the share that is served by ip.

            Multiple shares can have same dir path but
            can be served using different ips. It finds the
            share which is served by ip on same nfs server.
        """
        ip_vserver = self._get_vserver_for_ip(ip)
        if ip_vserver and shares:
            for share in shares:
                ip_sh, __ = na_utils.get_export_host_junction_path(share)
                sh_vserver = self._get_vserver_for_ip(ip_sh)
                if sh_vserver == ip_vserver:
                    LOG.debug('Share match found for ip %s', ip)
                    return share
        LOG.debug('No share match found for ip %s', ip)
        return None

    def _get_vserver_for_ip(self, ip):
        """Get vserver for the mentioned ip."""
        try:
            ifs = self.zapi_client.get_if_info_by_ip(ip)
            vserver = ifs[0].get_child_content('vserver')
            return vserver
        except Exception:
            return None

    def _is_share_clone_compatible(self, volume, share):
        """Checks if share is compatible with volume to host its clone."""
        flexvol_name = self._get_flexvol_name_for_share(share)
        return self._is_share_vol_type_match(volume, share, flexvol_name)

    def _is_share_vol_type_match(self, volume, share, flexvol_name):
        """Checks if share matches volume type."""
        LOG.debug("Found volume %(vol)s for share %(share)s.",
                  {'vol': flexvol_name, 'share': share})
        extra_specs = na_utils.get_volume_extra_specs(volume)
        flexvol_names = self.ssc_library.get_matching_flexvols_for_extra_specs(
            extra_specs)
        return flexvol_name in flexvol_names

    def _get_flexvol_name_for_share(self, nfs_share):
        """Queries the SSC for the flexvol containing an NFS share."""
        ssc = self.ssc_library.get_ssc()
        for ssc_vol_name, ssc_vol_info in ssc.items():
            if nfs_share == ssc_vol_info.get('pool_name'):
                return ssc_vol_name
        return None

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        self._delete_backing_file_for_volume(volume)
        try:
            qos_policy_group_info = na_utils.get_valid_qos_policy_group_info(
                volume)
            self.zapi_client.mark_qos_policy_group_for_deletion(
                qos_policy_group_info)
        except Exception:
            # Don't blow up here if something went wrong de-provisioning the
            # QoS policy for the volume.
            pass

    def _delete_backing_file_for_volume(self, volume):
        """Deletes file on nfs share that backs a cinder volume."""
        try:
            LOG.debug('Deleting backing file for volume %s.', volume['id'])
            self._delete_file(volume['id'], volume['name'])
        except Exception:
            LOG.exception('Could not delete volume %s on backend, '
                          'falling back to exec of "rm" command.',
                          volume['id'])
            try:
                super(NetAppCmodeNfsDriver, self).delete_volume(volume)
            except Exception:
                LOG.exception('Exec of "rm" command on backing file for '
                              '%s was unsuccessful.', volume['id'])

    def _delete_file(self, file_id, file_name):
        (host_ip, junction_path) = self._get_export_ip_path(volume_id=file_id)
        vserver = self._get_vserver_for_ip(host_ip)
        flexvol = self.zapi_client.get_vol_by_junc_vserver(
            vserver, junction_path)
        path_on_backend = '/vol/' + flexvol + '/' + file_name
        LOG.debug('Attempting to delete file %(path)s for ID %(file_id)s on '
                  'backend.', {'path': path_on_backend, 'file_id': file_id})
        self.zapi_client.delete_file(path_on_backend)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self._delete_backing_file_for_snapshot(snapshot)

    def _delete_backing_file_for_snapshot(self, snapshot):
        """Deletes file on nfs share that backs a cinder volume."""
        try:
            LOG.debug('Deleting backing file for snapshot %s.', snapshot['id'])
            self._delete_file(snapshot['volume_id'], snapshot['name'])
        except Exception:
            LOG.exception('Could not delete snapshot %s on backend, '
                          'falling back to exec of "rm" command.',
                          snapshot['id'])
            try:
                # delete_file_from_share
                super(NetAppCmodeNfsDriver, self).delete_snapshot(snapshot)
            except Exception:
                LOG.exception('Exec of "rm" command on backing file for'
                              ' %s was unsuccessful.', snapshot['id'])

    def _get_ip_verify_on_cluster(self, host):
        """Verifies if host on same cluster and returns ip."""
        ip = utils.resolve_hostname(host)
        vserver = self._get_vserver_for_ip(ip)
        if not vserver:
            raise exception.NotFound(_("Unable to locate an SVM that is "
                                       "managing the IP address '%s'") % ip)
        return ip

    def _copy_from_cache(self, volume, image_id, cache_result):
        """Try copying image file_name from cached file_name."""
        copied = False
        cache_copy, found_local = self._find_image_location(cache_result,
                                                            volume)

        try:
            if found_local:
                LOG.debug("Trying copy from cache using cloning.")
                (nfs_share, file_name) = cache_copy
                self._clone_file_dst_exists(
                    nfs_share, file_name, volume['name'], dest_exists=True)
                LOG.debug("Copied image from cache to volume %s using "
                          "cloning.", volume['id'])
                copied = True
            elif (cache_copy and
                  self.configuration.netapp_copyoffload_tool_path):
                LOG.debug("Trying copy from cache using copy offload.")
                self._copy_from_remote_cache(volume, image_id, cache_copy)
                copied = True
        except Exception:
            LOG.exception('Error in workflow copy from cache.')
        return copied

    def _find_image_location(self, cache_result, volume):
        """Finds the location of a cached image.

        Returns image location local to the NFS share, that matches the
        volume_id, if it exists. Otherwise returns the last entry in
        cache_result or None if cache_result is empty.
        """

        found_local_copy = False
        cache_copy = None

        provider_location = volume_utils.extract_host(volume['host'],
                                                      level='pool')

        for res in cache_result:
            (share, file_name) = res
            if share == provider_location:
                cache_copy = res
                found_local_copy = True
                break
            else:
                cache_copy = res
        return cache_copy, found_local_copy

    def _copy_from_remote_cache(self, volume, image_id, cache_copy):
        """Copies the remote cached image to the provided volume.

        Executes the copy offload binary which copies the cached image to
        the destination path of the provided volume. Also registers the new
        copy of the image as a cached image.
        """

        (nfs_share, file_name) = cache_copy
        col_path = self.configuration.netapp_copyoffload_tool_path
        src_ip, src_path = self._get_source_ip_and_path(nfs_share, file_name)
        dest_ip, dest_path = self._get_destination_ip_and_path(volume)

        # Always run copy offload as regular user, it's sufficient
        # and rootwrap doesn't allow copy offload to run as root anyways.
        self._execute(col_path, src_ip, dest_ip, src_path, dest_path,
                      run_as_root=False, check_exit_code=0)
        self._register_image_in_cache(volume, image_id)
        LOG.debug("Copied image from cache to volume %s using copy offload.",
                  volume['id'])

    def _get_source_ip_and_path(self, nfs_share, file_name):
        host, share_path = na_utils.get_export_host_junction_path(nfs_share)
        src_ip = self._get_ip_verify_on_cluster(host)
        src_path = os.path.join(share_path, file_name)

        return src_ip, src_path

    def _get_destination_ip_and_path(self, volume):
        share = volume_utils.extract_host(volume['host'], level='pool')
        share_ip, share_path = na_utils.get_export_host_junction_path(share)
        dest_ip = self._get_ip_verify_on_cluster(share_ip)
        dest_path = os.path.join(share_path, volume['name'])

        return dest_ip, dest_path

    def _clone_file_dst_exists(self, share, src_name, dst_name,
                               dest_exists=False):
        """Clone file even if dest exists."""
        (vserver, exp_volume) = self._get_vserver_and_exp_vol(share=share)
        self.zapi_client.clone_file(exp_volume, src_name, dst_name, vserver,
                                    dest_exists=dest_exists)

    def _copy_from_img_service(self, context, volume, image_service,
                               image_id):
        """Copies from the image service using copy offload."""

        LOG.debug("Trying copy from image service using copy offload.")
        image_loc = image_service.get_location(context, image_id)
        locations = self._construct_image_nfs_url(image_loc)
        src_ip = None
        selected_loc = None
        cloned = False

        # this will match the first location that has a valid IP on cluster
        for location in locations:
            conn, dr = self._check_get_nfs_path_segs(location)
            if conn:
                try:
                    src_ip = self._get_ip_verify_on_cluster(conn.split(':')[0])
                    selected_loc = location
                    break
                except exception.NotFound:
                    pass
        if src_ip is None:
            raise exception.NotFound(_("Source host details not found."))
        (__, ___, img_file) = selected_loc.rpartition('/')
        src_path = os.path.join(dr, img_file)

        dst_ip, vol_path = self._get_destination_ip_and_path(volume)
        share_path = vol_path.rsplit("/", 1)[0]
        dst_share = dst_ip + ':' + share_path

        # tmp file is required to deal with img formats
        tmp_img_file = six.text_type(uuid.uuid4())
        col_path = self.configuration.netapp_copyoffload_tool_path
        img_info = image_service.show(context, image_id)
        self._check_share_can_hold_size(dst_share, img_info['size'])
        run_as_root = self._execute_as_root

        dst_dir = self._get_mount_point_for_share(dst_share)
        dst_img_local = os.path.join(dst_dir, tmp_img_file)

        try:
            dst_img_serv_path = os.path.join(
                share_path, tmp_img_file)
            # Always run copy offload as regular user, it's sufficient
            # and rootwrap doesn't allow copy offload to run as root
            # anyways.
            self._execute(col_path, src_ip, dst_ip, src_path,
                          dst_img_serv_path, run_as_root=False,
                          check_exit_code=0)

            self._discover_file_till_timeout(dst_img_local, timeout=120)
            LOG.debug('Copied image %(img)s to tmp file %(tmp)s.',
                      {'img': image_id, 'tmp': tmp_img_file})
            dst_img_cache_local = os.path.join(dst_dir,
                                               'img-cache-%s' % image_id)
            if img_info['disk_format'] == 'raw':
                LOG.debug('Image is raw %s.', image_id)
                self._clone_file_dst_exists(dst_share, tmp_img_file,
                                            volume['name'], dest_exists=True)
                self._move_nfs_file(dst_img_local, dst_img_cache_local)
                LOG.debug('Copied raw image %(img)s to volume %(vol)s.',
                          {'img': image_id, 'vol': volume['id']})
            else:
                LOG.debug('Image will be converted to raw %s.', image_id)
                img_conv = six.text_type(uuid.uuid4())
                dst_img_conv_local = os.path.join(dst_dir, img_conv)

                # Checking against image size which is approximate check
                self._check_share_can_hold_size(dst_share, img_info['size'])
                try:
                    image_utils.convert_image(dst_img_local,
                                              dst_img_conv_local, 'raw',
                                              run_as_root=run_as_root)
                    data = image_utils.qemu_img_info(dst_img_conv_local,
                                                     run_as_root=run_as_root)
                    if data.file_format != "raw":
                        raise exception.InvalidResults(
                            _("Converted to raw, but format is now %s.")
                            % data.file_format)
                    else:
                        self._clone_file_dst_exists(dst_share, img_conv,
                                                    volume['name'],
                                                    dest_exists=True)
                        self._move_nfs_file(dst_img_conv_local,
                                            dst_img_cache_local)
                        LOG.debug('Copied locally converted raw image'
                                  ' %(img)s to volume %(vol)s.',
                                  {'img': image_id, 'vol': volume['id']})
                finally:
                    if os.path.exists(dst_img_conv_local):
                        self._delete_file_at_path(dst_img_conv_local)
            cloned = True
        finally:
            if os.path.exists(dst_img_local):
                self._delete_file_at_path(dst_img_local)

        return cloned

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

           Does not delete the underlying backend storage object. A log entry
           will be made to notify the Admin that the volume is no longer being
           managed.

           :param volume: Cinder volume to unmanage
        """
        try:
            qos_policy_group_info = na_utils.get_valid_qos_policy_group_info(
                volume)
            self.zapi_client.mark_qos_policy_group_for_deletion(
                qos_policy_group_info)
        except Exception:
            # Unmanage even if there was a problem deprovisioning the
            # associated qos policy group.
            pass

        super(NetAppCmodeNfsDriver, self).unmanage(volume)

    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        """Failover a backend to a secondary replication target."""

        return self._failover_host(volumes, secondary_id=secondary_id)

    def _get_backing_flexvol_names(self):
        """Returns a list of backing flexvol names."""

        ssc = self.ssc_library.get_ssc()
        return list(ssc.keys())

    def _get_flexvol_names_from_hosts(self, hosts):
        """Returns a set of flexvol names."""
        flexvols = set()
        ssc = self.ssc_library.get_ssc()

        for host in hosts:
            pool_name = volume_utils.extract_host(host, level='pool')

            for flexvol_name, ssc_volume_data in ssc.items():
                if ssc_volume_data['pool_name'] == pool_name:
                    flexvols.add(flexvol_name)

        return flexvols

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Delete files backing each snapshot in the group snapshot.

        :return: An implicit update of snapshot models that the manager will
                 interpret and subsequently set the model state to deleted.
        """
        for snapshot in snapshots:
            self._delete_backing_file_for_snapshot(snapshot)
            LOG.debug("Snapshot %s deletion successful", snapshot['name'])

        return None, None

    def create_group(self, context, group):
        """Driver entry point for creating a generic volume group.

        ONTAP does not maintain an actual group construct. As a result, no
        communtication to the backend is necessary for generic volume group
        creation.

        :returns: Hard-coded model update for generic volume group model.
        """
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        return model_update

    def delete_group(self, context, group, volumes):
        """Driver entry point for deleting a generic volume group.

        :returns: Updated group model and list of volume models for the volumes
                 that were deleted.
        """
        model_update = {'status': fields.GroupStatus.DELETED}
        volumes_model_update = []
        for volume in volumes:
            try:
                self._delete_file(volume['id'], volume['name'])
                volumes_model_update.append(
                    {'id': volume['id'], 'status': 'deleted'})
            except Exception:
                volumes_model_update.append(
                    {'id': volume['id'],
                     'status': fields.GroupStatus.ERROR_DELETING})
                LOG.exception("Volume %(vol)s in the group could not be "
                              "deleted.", {'vol': volume})
        return model_update, volumes_model_update

    def update_group(self, context, group, add_volumes=None,
                     remove_volumes=None):
        """Driver entry point for updating a generic volume group.

        Since no actual group construct is ever created in ONTAP, it is not
        necessary to update any metadata on the backend. Since this is a NO-OP,
        there is guaranteed to be no change in any of the volumes' statuses.
        """

        return None, None, None

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a Cinder group snapshot object.

        The Cinder group snapshot object is created by making use of an ONTAP
        consistency group snapshot in order to provide write-order consistency
        for a set of flexvols snapshots. First, a list of the flexvols backing
        the given Cinder group must be gathered. An ONTAP group-snapshot of
        these flexvols will create a snapshot copy of all the Cinder volumes in
        the generic volume group. For each Cinder volume in the group, it is
        then necessary to clone its backing file from the ONTAP cg-snapshot.
        The naming convention used to for the clones is what indicates the
        clone's role as a Cinder snapshot and its inclusion in a Cinder group.
        The ONTAP cg-snapshot of the flexvols is deleted after the cloning
        operation is completed.

        :returns: An implicit update for the group snapshot and snapshot models
                 that is then used by the manager to set the models to
                 available.
        """
        try:
            if volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
                self._create_consistent_group_snapshot(group_snapshot,
                                                       snapshots)
            else:
                for snapshot in snapshots:
                    self._clone_backing_file_for_volume(
                        snapshot['volume_name'], snapshot['name'],
                        snapshot['volume_id'], is_snapshot=True)
        except Exception as ex:
            err_msg = (_("Create group snapshot failed (%s).") % ex)
            LOG.exception(err_msg, resource=group_snapshot)
            raise exception.NetAppDriverException(err_msg)

        return None, None

    def _create_consistent_group_snapshot(self, group_snapshot, snapshots):
        hosts = [snapshot['volume']['host'] for snapshot in snapshots]
        flexvols = self._get_flexvol_names_from_hosts(hosts)

        # Create snapshot for backing flexvol
        self.zapi_client.create_cg_snapshot(flexvols, group_snapshot['id'])

        # Start clone process for snapshot files
        for snapshot in snapshots:
            self._clone_backing_file_for_volume(
                snapshot['volume']['name'], snapshot['name'],
                snapshot['volume']['id'], source_snapshot=group_snapshot['id'])

        # Delete backing flexvol snapshots
        for flexvol_name in flexvols:
            try:
                self.zapi_client.wait_for_busy_snapshot(
                    flexvol_name, group_snapshot['id'])
                self.zapi_client.delete_snapshot(
                    flexvol_name, group_snapshot['id'])
            except exception.SnapshotIsBusy:
                self.zapi_client.mark_snapshot_for_deletion(
                    flexvol_name, group_snapshot['id'])

    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, sorted_snapshots=None,
                              source_group=None, sorted_source_vols=None):
        """Creates a group from a group snapshot or a group of cinder vols.

        :returns: An implicit update for the volumes model that is
                 interpreted by the manager as a successful operation.
        """
        LOG.debug("VOLUMES %s ", ', '.join([vol['id'] for vol in volumes]))
        model_update = None
        volumes_model_update = []

        if group_snapshot:
            vols = zip(volumes, sorted_snapshots)

            for volume, snapshot in vols:
                update = self.create_volume_from_snapshot(
                    volume, snapshot)
                update['id'] = volume['id']
                volumes_model_update.append(update)

        elif source_group and sorted_source_vols:
            hosts = [source_vol['host'] for source_vol in sorted_source_vols]
            flexvols = self._get_flexvol_names_from_hosts(hosts)

            # Create snapshot for backing flexvol
            snapshot_name = 'snapshot-temp-' + source_group['id']
            self.zapi_client.create_cg_snapshot(flexvols, snapshot_name)

            # Start clone process for new volumes
            vols = zip(volumes, sorted_source_vols)
            for volume, source_vol in vols:
                self._clone_backing_file_for_volume(
                    source_vol['name'], volume['name'],
                    source_vol['id'], source_snapshot=snapshot_name)
                volume_model_update = (
                    self._get_volume_model_update(volume) or {})
                volume_model_update.update({
                    'id': volume['id'],
                    'provider_location': source_vol['provider_location'],
                })
                volumes_model_update.append(volume_model_update)

            # Delete backing flexvol snapshots
            for flexvol_name in flexvols:
                self.zapi_client.wait_for_busy_snapshot(
                    flexvol_name, snapshot_name)
                self.zapi_client.delete_snapshot(flexvol_name, snapshot_name)
        else:
            LOG.error("Unexpected set of parameters received when "
                      "creating group from source.")
            model_update = {'status': fields.GroupStatus.ERROR}

        return model_update, volumes_model_update
