# Copyright (c) 2012 NetApp, Inc.  All rights reserved.
# Copyright (c) 2014 Ben Swartzlander.  All rights reserved.
# Copyright (c) 2014 Navneet Singh.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Andrew Kerr.  All rights reserved.
# Copyright (c) 2014 Jeff Applewhite.  All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
# Copyright (c) 2015 Goutham Pacha Ravi. All rights reserved.
# Copyright (c) 2016 Mike Rooney. All rights reserved.
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

from oslo_log import log as logging
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder import utils
from cinder.volume.drivers.netapp.dataontap import block_base
from cinder.volume.drivers.netapp.dataontap.performance import perf_cmode
from cinder.volume.drivers.netapp.dataontap.utils import capabilities
from cinder.volume.drivers.netapp.dataontap.utils import data_motion
from cinder.volume.drivers.netapp.dataontap.utils import loopingcalls
from cinder.volume.drivers.netapp.dataontap.utils import utils as dot_utils
from cinder.volume.drivers.netapp import options as na_opts
from cinder.volume.drivers.netapp import utils as na_utils


LOG = logging.getLogger(__name__)


@six.add_metaclass(utils.TraceWrapperMetaclass)
class NetAppBlockStorageCmodeLibrary(block_base.NetAppBlockStorageLibrary,
                                     data_motion.DataMotionMixin):
    """NetApp block storage library for Data ONTAP (Cluster-mode)."""

    REQUIRED_CMODE_FLAGS = ['netapp_vserver']

    def __init__(self, driver_name, driver_protocol, **kwargs):
        super(NetAppBlockStorageCmodeLibrary, self).__init__(driver_name,
                                                             driver_protocol,
                                                             **kwargs)
        self.configuration.append_config_values(na_opts.netapp_cluster_opts)
        self.driver_mode = 'cluster'
        self.failed_over_backend_name = kwargs.get('active_backend_id')
        self.failed_over = self.failed_over_backend_name is not None
        self.replication_enabled = (
            True if self.get_replication_backend_names(
                self.configuration) else False)

    def do_setup(self, context):
        super(NetAppBlockStorageCmodeLibrary, self).do_setup(context)
        na_utils.check_flags(self.REQUIRED_CMODE_FLAGS, self.configuration)

        # cDOT API client
        self.zapi_client = dot_utils.get_client_for_backend(
            self.failed_over_backend_name or self.backend_name)
        self.vserver = self.zapi_client.vserver
        self.using_cluster_credentials = \
            self.zapi_client.check_for_cluster_credentials()

        # Performance monitoring library
        self.perf_library = perf_cmode.PerformanceCmodeLibrary(
            self.zapi_client)

        # Storage service catalog
        self.ssc_library = capabilities.CapabilitiesLibrary(
            self.driver_protocol, self.vserver, self.zapi_client,
            self.configuration)

    def _update_zapi_client(self, backend_name):
        """Set cDOT API client for the specified config backend stanza name."""

        self.zapi_client = dot_utils.get_client_for_backend(backend_name)
        self.vserver = self.zapi_client.vserver
        self.ssc_library._update_for_failover(self.zapi_client,
                                              self._get_flexvol_to_pool_map())
        ssc = self.ssc_library.get_ssc()
        self.perf_library._update_for_failover(self.zapi_client, ssc)
        # Clear LUN table cache
        self.lun_table = {}

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate."""
        self.ssc_library.check_api_permissions()

        if not self._get_flexvol_to_pool_map():
            msg = _('No pools are available for provisioning volumes. '
                    'Ensure that the configuration option '
                    'netapp_pool_name_search_pattern is set correctly.')
            raise exception.NetAppDriverException(msg)
        self._add_looping_tasks()
        super(NetAppBlockStorageCmodeLibrary, self).check_for_setup_error()

    def _add_looping_tasks(self):
        """Add tasks that need to be executed at a fixed interval."""

        # Note(cknight): Run the update once in the current thread to prevent a
        # race with the first invocation of _update_volume_stats.
        self._update_ssc()

        # Add the task that updates the slow-changing storage service catalog
        self.loopingcalls.add_task(self._update_ssc,
                                   loopingcalls.ONE_HOUR,
                                   loopingcalls.ONE_HOUR)

        # Add the task that harvests soft-deleted QoS policy groups.
        self.loopingcalls.add_task(
            self.zapi_client.remove_unused_qos_policy_groups,
            loopingcalls.ONE_MINUTE,
            loopingcalls.ONE_MINUTE)

        self.loopingcalls.add_task(
            self._handle_housekeeping_tasks,
            loopingcalls.TEN_MINUTES,
            0)

        super(NetAppBlockStorageCmodeLibrary, self)._add_looping_tasks()

    def _handle_housekeeping_tasks(self):
        """Handle various cleanup activities."""

        # Harvest soft-deleted QoS policy groups
        self.zapi_client.remove_unused_qos_policy_groups()

        active_backend = self.failed_over_backend_name or self.backend_name

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

    def _handle_ems_logging(self):
        """Log autosupport messages."""

        base_ems_message = dot_utils.build_ems_log_message_0(
            self.driver_name, self.app_version, self.driver_mode)
        self.zapi_client.send_ems_log_message(base_ems_message)

        pool_ems_message = dot_utils.build_ems_log_message_1(
            self.driver_name, self.app_version, self.vserver,
            self.ssc_library.get_ssc_flexvol_names(), [])
        self.zapi_client.send_ems_log_message(pool_ems_message)

    def _create_lun(self, volume_name, lun_name, size,
                    metadata, qos_policy_group_name=None):
        """Creates a LUN, handling Data ONTAP differences as needed."""

        self.zapi_client.create_lun(
            volume_name, lun_name, size, metadata, qos_policy_group_name)

    def _create_lun_handle(self, metadata, vserver=None):
        """Returns LUN handle based on filer type."""
        vserver = vserver or self.vserver
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
                   block_count=0, source_snapshot=None, is_snapshot=False):
        """Clone LUN with the given handle to the new name."""
        if not space_reserved:
            space_reserved = self.lun_space_reservation
        metadata = self._get_lun_attr(name, 'metadata')
        volume = metadata['Volume']

        self.zapi_client.clone_lun(volume, name, new_name, space_reserved,
                                   qos_policy_group_name=qos_policy_group_name,
                                   src_block=src_block, dest_block=dest_block,
                                   block_count=block_count,
                                   source_snapshot=source_snapshot,
                                   is_snapshot=is_snapshot)

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

    def _update_volume_stats(self, filter_function=None,
                             goodness_function=None):
        """Retrieve backend stats."""

        LOG.debug('Updating volume stats')
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.driver_name
        data['vendor_name'] = 'NetApp'
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = self.driver_protocol
        data['pools'] = self._get_pool_stats(
            filter_function=filter_function,
            goodness_function=goodness_function)
        data['sparse_copy_volume'] = True

        # Used for service state report
        data['replication_enabled'] = self.replication_enabled

        self._stats = data

    def _get_pool_stats(self, filter_function=None, goodness_function=None):
        """Retrieve pool (Data ONTAP flexvol) stats.

        Pool statistics are assembled from static driver capabilities, the
        Storage Service Catalog of flexvol attributes, and real-time capacity
        and controller utilization metrics.  The pool name is the flexvol name.
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
            pool['QoS_support'] = True
            pool['multiattach'] = True
            pool['consistencygroup_support'] = True
            pool['reserved_percentage'] = self.reserved_percentage
            pool['max_over_subscription_ratio'] = (
                self.max_over_subscription_ratio)

            # Add up-to-date capacity info
            capacity = self.zapi_client.get_flexvol_capacity(
                flexvol_name=ssc_vol_name)

            size_total_gb = capacity['size-total'] / units.Gi
            pool['total_capacity_gb'] = na_utils.round_down(size_total_gb)

            size_available_gb = capacity['size-available'] / units.Gi
            pool['free_capacity_gb'] = na_utils.round_down(size_available_gb)

            pool['provisioned_capacity_gb'] = round(
                pool['total_capacity_gb'] - pool['free_capacity_gb'], 2)

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

        self.ssc_library.update_ssc(self._get_flexvol_to_pool_map())

    def _get_flexvol_to_pool_map(self):
        """Get the flexvols that match the pool name search pattern.

        The map is of the format suitable for seeding the storage service
        catalog: {<flexvol_name> : {'pool_name': <flexvol_name>}}
        """

        pool_regex = na_utils.get_pool_name_filter_regex(self.configuration)

        pools = {}
        flexvol_names = self.zapi_client.list_flexvols()

        for flexvol_name in flexvol_names:

            msg_args = {
                'flexvol': flexvol_name,
                'vol_pattern': pool_regex.pattern,
            }

            if pool_regex.match(flexvol_name):
                msg = "Volume '%(flexvol)s' matches %(vol_pattern)s"
                LOG.debug(msg, msg_args)
                pools[flexvol_name] = {'pool_name': flexvol_name}
            else:
                msg = "Volume '%(flexvol)s' does not match %(vol_pattern)s"
                LOG.debug(msg, msg_args)

        return pools

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        super(NetAppBlockStorageCmodeLibrary, self).delete_volume(volume)
        try:
            qos_policy_group_info = na_utils.get_valid_qos_policy_group_info(
                volume)
        except exception.Invalid:
            # Delete even if there was invalid qos policy specified for the
            # volume.
            qos_policy_group_info = None
        self._mark_qos_policy_group_for_deletion(qos_policy_group_info)

        msg = 'Deleted LUN with name %(name)s and QoS info %(qos)s'
        LOG.debug(msg, {'name': volume['name'], 'qos': qos_policy_group_info})

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
            self.zapi_client.get_operational_lif_addresses())

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

    def _get_volume_model_update(self, volume):
        """Provide any updates necessary for a volume being created/managed."""
        if self.replication_enabled:
            return {'replication_status': fields.ReplicationStatus.ENABLED}

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

    def failover_host(self, context, volumes, secondary_id=None):
        """Failover a backend to a secondary replication target."""

        return self._failover_host(volumes, secondary_id=secondary_id)

    def _get_backing_flexvol_names(self):
        """Returns a list of backing flexvol names."""
        return self.ssc_library.get_ssc().keys()
