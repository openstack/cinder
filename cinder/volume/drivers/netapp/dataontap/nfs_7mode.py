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

from oslo_log import log as logging
import six

from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder.volume.drivers.netapp.dataontap.client import client_7mode
from cinder.volume.drivers.netapp.dataontap import nfs_base
from cinder.volume.drivers.netapp import options as na_opts
from cinder.volume.drivers.netapp import utils as na_utils


LOG = logging.getLogger(__name__)


@six.add_metaclass(utils.TraceWrapperWithABCMetaclass)
class NetApp7modeNfsDriver(nfs_base.NetAppNfsDriver):
    """NetApp NFS driver for Data ONTAP (7-mode)."""

    def __init__(self, *args, **kwargs):
        super(NetApp7modeNfsDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(na_opts.netapp_7mode_opts)

    def do_setup(self, context):
        """Do the customized set up on client if any for 7 mode."""
        super(NetApp7modeNfsDriver, self).do_setup(context)

        self.zapi_client = client_7mode.Client(
            transport_type=self.configuration.netapp_transport_type,
            username=self.configuration.netapp_login,
            password=self.configuration.netapp_password,
            hostname=self.configuration.netapp_server_hostname,
            port=self.configuration.netapp_server_port,
            vfiler=self.configuration.netapp_vfiler)

        self.ssc_enabled = False

    def check_for_setup_error(self):
        """Checks if setup occurred properly."""
        api_version = self.zapi_client.get_ontapi_version()
        if api_version:
            major, minor = api_version
            if major == 1 and minor < 9:
                msg = _("Unsupported Data ONTAP version."
                        " Data ONTAP version 7.3.1 and above is supported.")
                raise exception.VolumeBackendAPIException(data=msg)
        else:
            msg = _("Data ONTAP API version could not be determined.")
            raise exception.VolumeBackendAPIException(data=msg)
        super(NetApp7modeNfsDriver, self).check_for_setup_error()

    def _clone_backing_file_for_volume(self, volume_name, clone_name,
                                       volume_id, share=None):
        """Clone backing file for Cinder volume."""

        (_host_ip, export_path) = self._get_export_ip_path(volume_id, share)
        storage_path = self.zapi_client.get_actual_path_for_export(export_path)
        target_path = '%s/%s' % (storage_path, clone_name)
        self.zapi_client.clone_file('%s/%s' % (storage_path, volume_name),
                                    target_path)

    def _update_volume_stats(self):
        """Retrieve stats info from vserver."""

        self._ensure_shares_mounted()

        LOG.debug('Updating volume stats')
        data = {}
        netapp_backend = 'NetApp_NFS_7mode_direct'
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or netapp_backend
        data['vendor_name'] = 'NetApp'
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = 'nfs'
        data['pools'] = self._get_pool_stats()

        self._spawn_clean_cache_job()
        self.zapi_client.provide_ems(self, netapp_backend, self._app_version,
                                     server_type="7mode")
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

            thick = not self.configuration.nfs_sparsed_volumes
            pool['thick_provisioning_support'] = thick
            pool['thin_provisioning_support'] = not thick

            pools.append(pool)

        return pools

    def _shortlist_del_eligible_files(self, share, old_files):
        """Prepares list of eligible files to be deleted from cache."""
        file_list = []
        (_, export_path) = self._get_export_ip_path(share=share)
        exported_volume = self.zapi_client.get_actual_path_for_export(
            export_path)
        for old_file in old_files:
            path = os.path.join(exported_volume, old_file)
            u_bytes = self.zapi_client.get_file_usage(path)
            file_list.append((old_file, u_bytes))
        LOG.debug('Shortlisted files eligible for deletion: %s', file_list)
        return file_list

    def _is_filer_ip(self, ip):
        """Checks whether ip is on the same filer."""
        try:
            ifconfig = self.zapi_client.get_ifconfig()
            if_info = ifconfig.get_child_by_name('interface-config-info')
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
                    LOG.debug('Share match found for ip %s', ip)
                    return share
        LOG.debug('No share match found for ip %s', ip)
        return None

    def _is_share_clone_compatible(self, volume, share):
        """Checks if share is compatible with volume to host its clone."""
        thin = self.configuration.nfs_sparsed_volumes
        return self._share_has_space_for_clone(share, volume['size'], thin)

    def _check_volume_type(self, volume, share, file_name, extra_specs):
        """Matches a volume type for share file."""
        qos_policy_group = extra_specs.pop('netapp:qos_policy_group', None) \
            if extra_specs else None
        if qos_policy_group:
            raise exception.ManageExistingVolumeTypeMismatch(
                reason=(_("Setting file qos policy group is not supported"
                          " on this storage family and ontap version.")))
        volume_type = na_utils.get_volume_type_from_volume(volume)
        if volume_type and 'qos_spec_id' in volume_type:
            raise exception.ManageExistingVolumeTypeMismatch(
                reason=_("QoS specs are not supported"
                         " on this storage family and ONTAP version."))

    def _do_qos_for_volume(self, volume, extra_specs, cleanup=False):
        """Set QoS policy on backend from volume type information."""
        # 7-mode DOT does not support QoS.
        return
