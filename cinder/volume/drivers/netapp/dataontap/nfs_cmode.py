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
import six

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.image import image_utils
from cinder import utils
from cinder.volume.drivers.netapp.dataontap.client import api as na_api
from cinder.volume.drivers.netapp.dataontap.client import client_cmode
from cinder.volume.drivers.netapp.dataontap import nfs_base
from cinder.volume.drivers.netapp.dataontap import ssc_cmode
from cinder.volume.drivers.netapp import options as na_opts
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)


class NetAppCmodeNfsDriver(nfs_base.NetAppNfsDriver):
    """NetApp NFS driver for Data ONTAP (Cluster-mode)."""

    REQUIRED_CMODE_FLAGS = ['netapp_vserver']

    def __init__(self, *args, **kwargs):
        super(NetAppCmodeNfsDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(na_opts.netapp_cluster_opts)

    def do_setup(self, context):
        """Do the customized set up on client for cluster mode."""
        super(NetAppCmodeNfsDriver, self).do_setup(context)
        na_utils.check_flags(self.REQUIRED_CMODE_FLAGS, self.configuration)

        self.vserver = self.configuration.netapp_vserver

        self.zapi_client = client_cmode.Client(
            transport_type=self.configuration.netapp_transport_type,
            username=self.configuration.netapp_login,
            password=self.configuration.netapp_password,
            hostname=self.configuration.netapp_server_hostname,
            port=self.configuration.netapp_server_port,
            vserver=self.vserver)

        self.ssc_enabled = True
        self.ssc_vols = None
        self.stale_vols = set()

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate."""
        super(NetAppCmodeNfsDriver, self).check_for_setup_error()
        ssc_cmode.check_ssc_api_permissions(self.zapi_client)

    def create_volume(self, volume):
        """Creates a volume.

        :param volume: volume reference
        """
        LOG.debug('create_volume on %s' % volume['host'])
        self._ensure_shares_mounted()

        # get share as pool name
        share = volume_utils.extract_host(volume['host'], level='pool')

        if share is None:
            msg = _("Pool is not available in the volume host field.")
            raise exception.InvalidHost(reason=msg)

        extra_specs = na_utils.get_volume_extra_specs(volume)
        qos_policy_group = extra_specs.pop('netapp:qos_policy_group', None) \
            if extra_specs else None

        # warn on obsolete extra specs
        na_utils.log_extra_spec_warnings(extra_specs)

        try:
            volume['provider_location'] = share
            LOG.info(_LI('casted to %s') % volume['provider_location'])
            self._do_create_volume(volume)
            if qos_policy_group:
                self._set_qos_policy_group_on_volume(volume, share,
                                                     qos_policy_group)
            return {'provider_location': volume['provider_location']}
        except Exception as ex:
            LOG.error(_LW("Exception creating vol %(name)s on "
                          "share %(share)s. Details: %(ex)s")
                      % {'name': volume['name'],
                         'share': volume['provider_location'],
                         'ex': ex})
            volume['provider_location'] = None
        finally:
            if self.ssc_enabled:
                self._update_stale_vols(self._get_vol_for_share(share))

        msg = _("Volume %s could not be created on shares.")
        raise exception.VolumeBackendAPIException(data=msg % (volume['name']))

    def _set_qos_policy_group_on_volume(self, volume, share, qos_policy_group):
        target_path = '%s' % (volume['name'])
        export_path = share.split(':')[1]
        flex_vol_name = self.zapi_client.get_vol_by_junc_vserver(self.vserver,
                                                                 export_path)
        self.zapi_client.file_assign_qos(flex_vol_name,
                                         qos_policy_group,
                                         target_path)

    def _check_volume_type(self, volume, share, file_name):
        """Match volume type for share file."""
        extra_specs = na_utils.get_volume_extra_specs(volume)
        qos_policy_group = extra_specs.pop('netapp:qos_policy_group', None) \
            if extra_specs else None
        if not self._is_share_vol_type_match(volume, share):
            raise exception.ManageExistingVolumeTypeMismatch(
                reason=(_("Volume type does not match for share %s."),
                        share))
        if qos_policy_group:
            try:
                vserver, flex_vol_name = self._get_vserver_and_exp_vol(
                    share=share)
                self.zapi_client.file_assign_qos(flex_vol_name,
                                                 qos_policy_group,
                                                 file_name)
            except na_api.NaApiError as ex:
                LOG.exception(_LE('Setting file QoS policy group failed. %s'),
                              ex)
                raise exception.NetAppDriverException(
                    reason=(_('Setting file QoS policy group failed. %s'), ex))

    def _clone_volume(self, volume_name, clone_name,
                      volume_id, share=None):
        """Clones mounted volume on NetApp Cluster."""
        (vserver, exp_volume) = self._get_vserver_and_exp_vol(volume_id, share)
        self.zapi_client.clone_file(exp_volume, volume_name, clone_name,
                                    vserver)
        share = share if share else self._get_provider_location(volume_id)
        self._post_prov_deprov_in_ssc(share)

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

        self._ensure_shares_mounted()
        sync = True if self.ssc_vols is None else False
        ssc_cmode.refresh_cluster_ssc(self, self.zapi_client.connection,
                                      self.vserver, synchronous=sync)

        LOG.debug('Updating volume stats')
        data = {}
        netapp_backend = 'NetApp_NFS_Cluster_direct'
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or netapp_backend
        data['vendor_name'] = 'NetApp'
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = 'nfs'
        data['pools'] = self._get_pool_stats()

        self._spawn_clean_cache_job()
        self.zapi_client.provide_ems(self, netapp_backend, self._app_version)
        self._stats = data

    def _get_pool_stats(self):
        """Retrieve pool (i.e. NFS share) stats info from SSC volumes."""

        pools = []

        for nfs_share in self._mounted_shares:

            capacity = self._get_share_capacity_info(nfs_share)

            pool = dict()
            pool['pool_name'] = nfs_share
            pool['QoS_support'] = False
            pool.update(capacity)

            # add SSC content if available
            vol = self._get_vol_for_share(nfs_share)
            if vol and self.ssc_vols:
                pool['netapp_raid_type'] = vol.aggr['raid_type']
                pool['netapp_disk_type'] = vol.aggr['disk_type']

                mirrored = vol in self.ssc_vols['mirrored']
                pool['netapp_mirrored'] = six.text_type(mirrored).lower()
                pool['netapp_unmirrored'] = six.text_type(not mirrored).lower()

                dedup = vol in self.ssc_vols['dedup']
                pool['netapp_dedup'] = six.text_type(dedup).lower()
                pool['netapp_nodedup'] = six.text_type(not dedup).lower()

                compression = vol in self.ssc_vols['compression']
                pool['netapp_compression'] = six.text_type(compression).lower()
                pool['netapp_nocompression'] = six.text_type(
                    not compression).lower()

                thin = vol in self.ssc_vols['thin']
                pool['netapp_thin_provisioned'] = six.text_type(thin).lower()
                pool['netapp_thick_provisioned'] = six.text_type(
                    not thin).lower()

            pools.append(pool)

        return pools

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
            LOG.warning(_LW("No shares found hence skipping ssc refresh."))
            return
        mnt_share_vols = set()
        vs_ifs = self.zapi_client.get_vserver_ips(self.vserver)
        for vol in vols['all']:
            for sh in self._mounted_shares:
                host = sh.split(':')[0]
                junction = sh.split(':')[1]
                ip = na_utils.resolve_hostname(host)
                if (self._ip_in_ifs(ip, vs_ifs) and
                        junction == vol.id['junction_path']):
                    mnt_share_vols.add(vol)
                    vol.export['path'] = sh
                    break
        for key in vols.keys():
            vols[key] = vols[key] & mnt_share_vols
        self.ssc_vols = vols

    def _ip_in_ifs(self, ip, api_ifs):
        """Checks if ip is listed for ifs in API format."""
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
            u_bytes = self.zapi_client.get_file_usage(path, vserver)
            file_list.append((file, u_bytes))
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
                ip_sh = share.split(':')[0]
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
        LOG.debug("Found volume %(vol)s for share %(share)s."
                  % {'vol': netapp_vol, 'share': share})
        extra_specs = na_utils.get_volume_extra_specs(volume)
        vols = ssc_cmode.get_volumes_for_specs(self.ssc_vols, extra_specs)
        return netapp_vol in vols

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        share = volume['provider_location']
        super(NetAppCmodeNfsDriver, self).delete_volume(volume)
        self._post_prov_deprov_in_ssc(share)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        share = self._get_provider_location(snapshot.volume_id)
        super(NetAppCmodeNfsDriver, self).delete_snapshot(snapshot)
        self._post_prov_deprov_in_ssc(share)

    def _post_prov_deprov_in_ssc(self, share):
        if self.ssc_enabled and share:
            netapp_vol = self._get_vol_for_share(share)
            if netapp_vol:
                self._update_stale_vols(volume=netapp_vol)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        copy_success = False
        try:
            major, minor = self.zapi_client.get_ontapi_version()
            col_path = self.configuration.netapp_copyoffload_tool_path
            if major == 1 and minor >= 20 and col_path:
                self._try_copyoffload(context, volume, image_service, image_id)
                copy_success = True
                LOG.info(_LI('Copied image %(img)s to volume %(vol)s using '
                             'copy offload workflow.')
                         % {'img': image_id, 'vol': volume['id']})
            else:
                LOG.debug("Copy offload either not configured or"
                          " unsupported.")
        except Exception as e:
            LOG.exception(_LE('Copy offload workflow unsuccessful. %s'), e)
        finally:
            if not copy_success:
                super(NetAppCmodeNfsDriver, self).copy_image_to_volume(
                    context, volume, image_service, image_id)
            if self.ssc_enabled:
                sh = self._get_provider_location(volume['id'])
                self._update_stale_vols(self._get_vol_for_share(sh))

    def _try_copyoffload(self, context, volume, image_service, image_id):
        """Tries server side file copy offload."""
        copied = False
        cache_result = self._find_image_in_cache(image_id)
        if cache_result:
            copied = self._copy_from_cache(volume, image_id, cache_result)
        if not cache_result or not copied:
            self._copy_from_img_service(context, volume, image_service,
                                        image_id)

    def _get_ip_verify_on_cluster(self, host):
        """Verifies if host on same cluster and returns ip."""
        ip = na_utils.resolve_hostname(host)
        vserver = self._get_vserver_for_ip(ip)
        if not vserver:
            raise exception.NotFound(_("Unable to locate an SVM that is "
                                       "managing the IP address '%s'") % ip)
        return ip

    def _copy_from_cache(self, volume, image_id, cache_result):
        """Try copying image file_name from cached file_name."""
        LOG.debug("Trying copy from cache using copy offload.")
        copied = False
        for res in cache_result:
            try:
                (share, file_name) = res
                LOG.debug("Found cache file_name on share %s.", share)
                if share != self._get_provider_location(volume['id']):
                    col_path = self.configuration.netapp_copyoffload_tool_path
                    src_ip = self._get_ip_verify_on_cluster(
                        share.split(':')[0])
                    src_path = os.path.join(share.split(':')[1], file_name)
                    dst_ip = self._get_ip_verify_on_cluster(self._get_host_ip(
                        volume['id']))
                    dst_path = os.path.join(
                        self._get_export_path(volume['id']), volume['name'])
                    # Always run copy offload as regular user, it's sufficient
                    # and rootwrap doesn't allow copy offload to run as root
                    # anyways.
                    self._execute(col_path, src_ip, dst_ip,
                                  src_path, dst_path,
                                  run_as_root=False,
                                  check_exit_code=0)
                    self._register_image_in_cache(volume, image_id)
                    LOG.debug("Copied image from cache to volume %s using"
                              " copy offload.", volume['id'])
                else:
                    self._clone_file_dst_exists(share, file_name,
                                                volume['name'],
                                                dest_exists=True)
                    LOG.debug("Copied image from cache to volume %s using"
                              " cloning.", volume['id'])
                self._post_clone_image(volume)
                copied = True
                break
            except Exception as e:
                LOG.exception(_LE('Error in workflow copy from cache. %s.'), e)
        return copied

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
        # this will match the first location that has a valid IP on cluster
        for location in locations:
            conn, dr = self._check_get_nfs_path_segs(location)
            if conn:
                try:
                    src_ip = self._get_ip_verify_on_cluster(conn.split(':')[0])
                    selected_loc = location
                    break
                except Exception.NotFound:
                    pass
        if src_ip is None:
            raise exception.NotFound(_("Source host details not found."))
        (__, ___, img_file) = selected_loc.rpartition('/')
        src_path = os.path.join(dr, img_file)
        dst_ip = self._get_ip_verify_on_cluster(self._get_host_ip(
            volume['id']))
        # tmp file is required to deal with img formats
        tmp_img_file = six.text_type(uuid.uuid4())
        col_path = self.configuration.netapp_copyoffload_tool_path
        img_info = image_service.show(context, image_id)
        dst_share = self._get_provider_location(volume['id'])
        self._check_share_can_hold_size(dst_share, img_info['size'])
        run_as_root = self._execute_as_root

        dst_dir = self._get_mount_point_for_share(dst_share)
        dst_img_local = os.path.join(dst_dir, tmp_img_file)
        try:
            # If src and dst share not equal
            if (('%s:%s' % (src_ip, dr)) !=
                    ('%s:%s' % (dst_ip, self._get_export_path(volume['id'])))):
                dst_img_serv_path = os.path.join(
                    self._get_export_path(volume['id']), tmp_img_file)
                # Always run copy offload as regular user, it's sufficient
                # and rootwrap doesn't allow copy offload to run as root
                # anyways.
                self._execute(col_path, src_ip, dst_ip, src_path,
                              dst_img_serv_path, run_as_root=False,
                              check_exit_code=0)
            else:
                self._clone_file_dst_exists(dst_share, img_file, tmp_img_file)
            self._discover_file_till_timeout(dst_img_local, timeout=120)
            LOG.debug('Copied image %(img)s to tmp file %(tmp)s.'
                      % {'img': image_id, 'tmp': tmp_img_file})
            dst_img_cache_local = os.path.join(dst_dir,
                                               'img-cache-%s' % image_id)
            if img_info['disk_format'] == 'raw':
                LOG.debug('Image is raw %s.', image_id)
                self._clone_file_dst_exists(dst_share, tmp_img_file,
                                            volume['name'], dest_exists=True)
                self._move_nfs_file(dst_img_local, dst_img_cache_local)
                LOG.debug('Copied raw image %(img)s to volume %(vol)s.'
                          % {'img': image_id, 'vol': volume['id']})
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
                                  ' %(img)s to volume %(vol)s.'
                                  % {'img': image_id, 'vol': volume['id']})
                finally:
                    if os.path.exists(dst_img_conv_local):
                        self._delete_file(dst_img_conv_local)
            self._post_clone_image(volume)
        finally:
            if os.path.exists(dst_img_local):
                self._delete_file(dst_img_local)
