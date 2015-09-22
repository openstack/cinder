# Copyright (c) 2012 NetApp, Inc.  All rights reserved.
# Copyright (c) 2014 Ben Swartzlander.  All rights reserved.
# Copyright (c) 2014 Navneet Singh.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Andrew Kerr.  All rights reserved.
# Copyright (c) 2014 Jeff Applewhite.  All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
# Copyright (c) 2015 Goutham Pacha Ravi. All rights reserved.
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
Volume driver library for NetApp C-mode block storage systems.
"""

import copy

from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder.volume.drivers.netapp.dataontap import block_base
from cinder.volume.drivers.netapp.dataontap.client import client_cmode
from cinder.volume.drivers.netapp.dataontap import ssc_cmode
from cinder.volume.drivers.netapp import options as na_opts
from cinder.volume.drivers.netapp import utils as na_utils


LOG = logging.getLogger(__name__)
QOS_CLEANUP_INTERVAL_SECONDS = 60


@six.add_metaclass(utils.TraceWrapperMetaclass)
class NetAppBlockStorageCmodeLibrary(block_base.NetAppBlockStorageLibrary):
    """NetApp block storage library for Data ONTAP (Cluster-mode)."""

    REQUIRED_CMODE_FLAGS = ['netapp_vserver']

    def __init__(self, driver_name, driver_protocol, **kwargs):
        super(NetAppBlockStorageCmodeLibrary, self).__init__(driver_name,
                                                             driver_protocol,
                                                             **kwargs)
        self.configuration.append_config_values(na_opts.netapp_cluster_opts)
        self.driver_mode = 'cluster'

    def do_setup(self, context):
        super(NetAppBlockStorageCmodeLibrary, self).do_setup(context)
        na_utils.check_flags(self.REQUIRED_CMODE_FLAGS, self.configuration)

        self.vserver = self.configuration.netapp_vserver

        self.zapi_client = client_cmode.Client(
            transport_type=self.configuration.netapp_transport_type,
            username=self.configuration.netapp_login,
            password=self.configuration.netapp_password,
            hostname=self.configuration.netapp_server_hostname,
            port=self.configuration.netapp_server_port,
            vserver=self.vserver)

        self.ssc_vols = {}
        self.stale_vols = set()

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate."""
        ssc_cmode.check_ssc_api_permissions(self.zapi_client)
        ssc_cmode.refresh_cluster_ssc(self, self.zapi_client.get_connection(),
                                      self.vserver, synchronous=True)
        if not self._get_filtered_pools():
            msg = _('No pools are available for provisioning volumes. '
                    'Ensure that the configuration option '
                    'netapp_pool_name_search_pattern is set correctly.')
            raise exception.NetAppDriverException(msg)
        super(NetAppBlockStorageCmodeLibrary, self).check_for_setup_error()
        self._start_periodic_tasks()

    def _start_periodic_tasks(self):
        # Start the task that harvests soft-deleted QoS policy groups.
        harvest_qos_periodic_task = loopingcall.FixedIntervalLoopingCall(
            self.zapi_client.remove_unused_qos_policy_groups)
        harvest_qos_periodic_task.start(
            interval=QOS_CLEANUP_INTERVAL_SECONDS,
            initial_delay=QOS_CLEANUP_INTERVAL_SECONDS)

    def _create_lun(self, volume_name, lun_name, size,
                    metadata, qos_policy_group_name=None):
        """Creates a LUN, handling Data ONTAP differences as needed."""

        self.zapi_client.create_lun(
            volume_name, lun_name, size, metadata, qos_policy_group_name)

        self._update_stale_vols(
            volume=ssc_cmode.NetAppVolume(volume_name, self.vserver))

    def _create_lun_handle(self, metadata):
        """Returns LUN handle based on filer type."""
        return '%s:%s' % (self.vserver, metadata['Path'])

    def _find_mapped_lun_igroup(self, path, initiator_list):
        """Find an igroup for a LUN mapped to the given initiator(s)."""
        initiator_igroups = self.zapi_client.get_igroup_by_initiators(
            initiator_list)
        lun_maps = self.zapi_client.get_lun_map(path)
        if initiator_igroups and lun_maps:
            for igroup in initiator_igroups:
                igroup_name = igroup['initiator-group-name']
                if igroup_name.startswith(na_utils.OPENSTACK_PREFIX):
                    for lun_map in lun_maps:
                        if lun_map['initiator-group'] == igroup_name:
                            return igroup_name, lun_map['lun-id']
        return None, None

    def _clone_lun(self, name, new_name, space_reserved=None,
                   qos_policy_group_name=None, src_block=0, dest_block=0,
                   block_count=0):
        """Clone LUN with the given handle to the new name."""
        if not space_reserved:
            space_reserved = self.lun_space_reservation
        metadata = self._get_lun_attr(name, 'metadata')
        volume = metadata['Volume']
        self.zapi_client.clone_lun(volume, name, new_name, space_reserved,
                                   qos_policy_group_name=qos_policy_group_name,
                                   src_block=0, dest_block=0,
                                   block_count=0)
        LOG.debug("Cloned LUN with new name %s", new_name)
        lun = self.zapi_client.get_lun_by_args(vserver=self.vserver,
                                               path='/vol/%s/%s'
                                               % (volume, new_name))
        if len(lun) == 0:
            msg = _("No cloned LUN named %s found on the filer")
            raise exception.VolumeBackendAPIException(data=msg % new_name)
        clone_meta = self._create_lun_meta(lun[0])
        self._add_lun_to_table(
            block_base.NetAppLun('%s:%s' % (clone_meta['Vserver'],
                                            clone_meta['Path']),
                                 new_name,
                                 lun[0].get_child_content('size'),
                                 clone_meta))
        self._update_stale_vols(
            volume=ssc_cmode.NetAppVolume(volume, self.vserver))

    def _create_lun_meta(self, lun):
        """Creates LUN metadata dictionary."""
        self.zapi_client.check_is_naelement(lun)
        meta_dict = {}
        meta_dict['Vserver'] = lun.get_child_content('vserver')
        meta_dict['Volume'] = lun.get_child_content('volume')
        meta_dict['Qtree'] = lun.get_child_content('qtree')
        meta_dict['Path'] = lun.get_child_content('path')
        meta_dict['OsType'] = lun.get_child_content('multiprotocol-type')
        meta_dict['SpaceReserved'] = \
            lun.get_child_content('is-space-reservation-enabled')
        meta_dict['UUID'] = lun.get_child_content('uuid')
        return meta_dict

    def _get_fc_target_wwpns(self, include_partner=True):
        return self.zapi_client.get_fc_target_wwpns()

    def _configure_tunneling(self, do_tunneling=False):
        """Configures tunneling for Data ONTAP cluster."""
        if do_tunneling:
            self.zapi_client.set_vserver(self.vserver)
        else:
            self.zapi_client.set_vserver(None)

    def _update_volume_stats(self):
        """Retrieve stats info from vserver."""

        sync = True if self.ssc_vols is None else False
        ssc_cmode.refresh_cluster_ssc(self, self.zapi_client.get_connection(),
                                      self.vserver, synchronous=sync)

        LOG.debug('Updating volume stats')
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.driver_name
        data['vendor_name'] = 'NetApp'
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = self.driver_protocol
        data['pools'] = self._get_pool_stats()

        self.zapi_client.provide_ems(self, self.driver_name, self.app_version)
        self._stats = data

    def _get_pool_stats(self):
        """Retrieve pool (Data ONTAP volume) stats info from SSC volumes."""

        pools = []

        if not self.ssc_vols:
            return pools

        for vol in self._get_filtered_pools():
            pool = dict()
            pool['pool_name'] = vol.id['name']
            pool['QoS_support'] = True
            pool['reserved_percentage'] = (
                self.reserved_percentage)
            pool['max_over_subscription_ratio'] = (
                self.max_over_subscription_ratio)

            # convert sizes to GB
            total = float(vol.space['size_total_bytes'])
            total /= units.Gi
            pool['total_capacity_gb'] = na_utils.round_down(total, '0.01')

            free = float(vol.space['size_avl_bytes'])
            free /= units.Gi
            pool['free_capacity_gb'] = na_utils.round_down(free, '0.01')

            pool['provisioned_capacity_gb'] = (round(
                pool['total_capacity_gb'] - pool['free_capacity_gb'], 2))

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
            pool['netapp_thick_provisioned'] = six.text_type(not thin).lower()
            thick = (not thin and
                     self.configuration.netapp_lun_space_reservation
                     == 'enabled')
            pool['thick_provisioned_support'] = thick
            pool['thin_provisioned_support'] = not thick

            pools.append(pool)

        return pools

    def _get_filtered_pools(self):
        """Return filtered pools given a pool name search pattern."""
        pool_regex = na_utils.get_pool_name_filter_regex(self.configuration)

        filtered_pools = []
        for vol in self.ssc_vols.get('all', []):
            vol_name = vol.id['name']
            if pool_regex.match(vol_name):
                msg = ("Volume '%(vol_name)s' matches against regular "
                       "expression: %(vol_pattern)s")
                LOG.debug(msg, {'vol_name': vol_name,
                                'vol_pattern': pool_regex.pattern})
                filtered_pools.append(vol)
            else:
                msg = ("Volume '%(vol_name)s' does not match against regular "
                       "expression: %(vol_pattern)s")
                LOG.debug(msg, {'vol_name': vol_name,
                                'vol_pattern': pool_regex.pattern})

        return filtered_pools

    @utils.synchronized('update_stale')
    def _update_stale_vols(self, volume=None, reset=False):
        """Populates stale vols with vol and returns set copy if reset."""
        if volume:
            self.stale_vols.add(volume)
        if reset:
            set_copy = copy.deepcopy(self.stale_vols)
            self.stale_vols.clear()
            return set_copy

    @utils.synchronized("refresh_ssc_vols")
    def refresh_ssc_vols(self, vols):
        """Refreshes ssc_vols with latest entries."""
        self.ssc_vols = vols

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        lun = self.lun_table.get(volume['name'])
        netapp_vol = None
        if lun:
            netapp_vol = lun.get_metadata_property('Volume')
        super(NetAppBlockStorageCmodeLibrary, self).delete_volume(volume)
        try:
            qos_policy_group_info = na_utils.get_valid_qos_policy_group_info(
                volume)
        except exception.Invalid:
            # Delete even if there was invalid qos policy specified for the
            # volume.
            qos_policy_group_info = None
        self._mark_qos_policy_group_for_deletion(qos_policy_group_info)
        if netapp_vol:
            self._update_stale_vols(
                volume=ssc_cmode.NetAppVolume(netapp_vol, self.vserver))
        msg = 'Deleted LUN with name %(name)s and QoS info %(qos)s'
        LOG.debug(msg, {'name': volume['name'], 'qos': qos_policy_group_info})

    def _check_volume_type_for_lun(self, volume, lun, existing_ref,
                                   extra_specs):
        """Check if LUN satisfies volume type."""
        def scan_ssc_data():
            volumes = ssc_cmode.get_volumes_for_specs(self.ssc_vols,
                                                      extra_specs)
            for vol in volumes:
                if lun.get_metadata_property('Volume') == vol.id['name']:
                    return True
            return False

        match_read = scan_ssc_data()
        if not match_read:
            ssc_cmode.get_cluster_latest_ssc(
                self, self.zapi_client.get_connection(), self.vserver)
            match_read = scan_ssc_data()

        if not match_read:
            raise exception.ManageExistingVolumeTypeMismatch(
                reason=(_("LUN with given ref %(ref)s does not satisfy volume"
                          " type. Ensure LUN volume with ssc features is"
                          " present on vserver %(vs)s.")
                        % {'ref': existing_ref, 'vs': self.vserver}))

    def _get_preferred_target_from_list(self, target_details_list,
                                        filter=None):
        # cDOT iSCSI LIFs do not migrate from controller to controller
        # in failover.  Rather, an iSCSI LIF must be configured on each
        # controller and the initiator has to take responsibility for
        # using a LIF that is UP.  In failover, the iSCSI LIF on the
        # downed controller goes DOWN until the controller comes back up.
        #
        # Currently Nova only accepts a single target when obtaining
        # target details from Cinder, so we pass back the first portal
        # with an UP iSCSI LIF.  There are plans to have Nova accept
        # and try multiple targets.  When that happens, we can and should
        # remove this filter and return all targets since their operational
        # state could change between the time we test here and the time
        # Nova uses the target.

        operational_addresses = (
            self.zapi_client.get_operational_network_interface_addresses())

        return (super(NetAppBlockStorageCmodeLibrary, self)
                ._get_preferred_target_from_list(target_details_list,
                                                 filter=operational_addresses))

    def _setup_qos_for_volume(self, volume, extra_specs):
        try:
            qos_policy_group_info = na_utils.get_valid_qos_policy_group_info(
                volume, extra_specs)
        except exception.Invalid:
            msg = _('Invalid QoS specification detected while getting QoS '
                    'policy for volume %s') % volume['id']
            raise exception.VolumeBackendAPIException(data=msg)
        self.zapi_client.provision_qos_policy_group(qos_policy_group_info)
        return qos_policy_group_info

    def _mark_qos_policy_group_for_deletion(self, qos_policy_group_info):
        self.zapi_client.mark_qos_policy_group_for_deletion(
            qos_policy_group_info)

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

           Does not delete the underlying backend storage object.
        """
        try:
            qos_policy_group_info = na_utils.get_valid_qos_policy_group_info(
                volume)
        except exception.Invalid:
            # Unmanage even if there was invalid qos policy specified for the
            # volume.
            qos_policy_group_info = None
        self._mark_qos_policy_group_for_deletion(qos_policy_group_info)
        super(NetAppBlockStorageCmodeLibrary, self).unmanage(volume)
