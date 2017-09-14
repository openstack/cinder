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
Volume driver library for NetApp 7-mode block storage systems.
"""

from oslo_log import log as logging
from oslo_log import versionutils
from oslo_utils import timeutils
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder import utils
from cinder.volume import configuration
from cinder.volume.drivers.netapp.dataontap import block_base
from cinder.volume.drivers.netapp.dataontap.client import client_7mode
from cinder.volume.drivers.netapp.dataontap.performance import perf_7mode
from cinder.volume.drivers.netapp.dataontap.utils import utils as dot_utils
from cinder.volume.drivers.netapp import options as na_opts
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume import utils as volume_utils


LOG = logging.getLogger(__name__)


@six.add_metaclass(utils.TraceWrapperMetaclass)
class NetAppBlockStorage7modeLibrary(block_base.NetAppBlockStorageLibrary):
    """NetApp block storage library for Data ONTAP (7-mode)."""

    def __init__(self, driver_name, driver_protocol, **kwargs):
        super(NetAppBlockStorage7modeLibrary, self).__init__(driver_name,
                                                             driver_protocol,
                                                             **kwargs)
        self.configuration.append_config_values(na_opts.netapp_7mode_opts)
        self.driver_mode = '7mode'

    def do_setup(self, context):
        super(NetAppBlockStorage7modeLibrary, self).do_setup(context)

        self.volume_list = []

        self.vfiler = self.configuration.netapp_vfiler

        self.zapi_client = client_7mode.Client(
            self.volume_list,
            transport_type=self.configuration.netapp_transport_type,
            username=self.configuration.netapp_login,
            password=self.configuration.netapp_password,
            hostname=self.configuration.netapp_server_hostname,
            port=self.configuration.netapp_server_port,
            vfiler=self.vfiler)

        self._do_partner_setup()

        self.vol_refresh_time = None
        self.vol_refresh_interval = 1800
        self.vol_refresh_running = False
        self.vol_refresh_voluntary = False
        self.root_volume_name = self._get_root_volume_name()
        self.perf_library = perf_7mode.Performance7modeLibrary(
            self.zapi_client)
        # This driver has been marked 'deprecated' in the Ocata release and
        # can be removed in Queens.
        msg = _("The 7-mode Data ONTAP driver is deprecated and will be "
                "removed in a future release.")
        versionutils.report_deprecated_feature(LOG, msg)

    def _do_partner_setup(self):
        partner_backend = self.configuration.netapp_partner_backend_name
        if partner_backend:
            config = configuration.Configuration(na_opts.netapp_7mode_opts,
                                                 partner_backend)
            config.append_config_values(na_opts.netapp_connection_opts)
            config.append_config_values(na_opts.netapp_basicauth_opts)
            config.append_config_values(na_opts.netapp_transport_opts)

            self.partner_zapi_client = client_7mode.Client(
                None,
                transport_type=config.netapp_transport_type,
                username=config.netapp_login,
                password=config.netapp_password,
                hostname=config.netapp_server_hostname,
                port=config.netapp_server_port,
                vfiler=None)

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate."""
        api_version = self.zapi_client.get_ontapi_version()
        if api_version:
            major, minor = api_version
            if major == 1 and minor < 9:
                msg = _("Unsupported Data ONTAP version."
                        " Data ONTAP version 7.3.1 and above is supported.")
                raise exception.VolumeBackendAPIException(data=msg)
        else:
            msg = _("API version could not be determined.")
            raise exception.VolumeBackendAPIException(data=msg)

        self._refresh_volume_info()

        if not self.volume_list:
            msg = _('No pools are available for provisioning volumes. '
                    'Ensure that the configuration option '
                    'netapp_pool_name_search_pattern is set correctly.')
            raise exception.NetAppDriverException(msg)
        self._add_looping_tasks()
        super(NetAppBlockStorage7modeLibrary, self).check_for_setup_error()

    def _add_looping_tasks(self):
        """Add tasks that need to be executed at a fixed interval."""
        super(NetAppBlockStorage7modeLibrary, self)._add_looping_tasks()

    def _handle_ems_logging(self):
        """Log autosupport messages."""

        base_ems_message = dot_utils.build_ems_log_message_0(
            self.driver_name, self.app_version, self.driver_mode)
        self.zapi_client.send_ems_log_message(base_ems_message)

        pool_ems_message = dot_utils.build_ems_log_message_1(
            self.driver_name, self.app_version, None, self.volume_list, [])
        self.zapi_client.send_ems_log_message(pool_ems_message)

    def _get_volume_model_update(self, volume):
        """Provide any updates necessary for a volume being created/managed."""

    def _create_lun(self, volume_name, lun_name, size,
                    metadata, qos_policy_group_name=None):
        """Creates a LUN, handling Data ONTAP differences as needed."""
        if qos_policy_group_name is not None:
            msg = _('Data ONTAP operating in 7-Mode does not support QoS '
                    'policy groups.')
            raise exception.VolumeDriverException(msg)
        self.zapi_client.create_lun(
            volume_name, lun_name, size, metadata, qos_policy_group_name)

        self.vol_refresh_voluntary = True

    def _get_root_volume_name(self):
        # switch to volume-get-root-name API when possible
        vols = self.zapi_client.get_filer_volumes()
        for vol in vols:
            volume_name = vol.get_child_content('name')
            if self._get_vol_option(volume_name, 'root') == 'true':
                return volume_name
        LOG.warning('Could not determine root volume name on %s.',
                    self._get_owner())
        return None

    def _get_owner(self):
        if self.vfiler:
            owner = '%s:%s' % (self.configuration.netapp_server_hostname,
                               self.vfiler)
        else:
            owner = self.configuration.netapp_server_hostname
        return owner

    def _create_lun_handle(self, metadata):
        """Returns LUN handle based on filer type."""
        owner = self._get_owner()
        return '%s:%s' % (owner, metadata['Path'])

    def _find_mapped_lun_igroup(self, path, initiator_list):
        """Find an igroup for a LUN mapped to the given initiator(s)."""
        initiator_set = set(initiator_list)

        result = self.zapi_client.get_lun_map(path)
        initiator_groups = result.get_child_by_name('initiator-groups')
        if initiator_groups:
            for initiator_group_info in initiator_groups.get_children():

                initiator_set_for_igroup = set()
                for initiator_info in initiator_group_info.get_child_by_name(
                        'initiators').get_children():
                    initiator_set_for_igroup.add(
                        initiator_info.get_child_content('initiator-name'))

                if initiator_set == initiator_set_for_igroup:
                    igroup = initiator_group_info.get_child_content(
                        'initiator-group-name')
                    lun_id = initiator_group_info.get_child_content(
                        'lun-id')
                    return igroup, lun_id

        return None, None

    def _has_luns_mapped_to_initiators(self, initiator_list,
                                       include_partner=True):
        """Checks whether any LUNs are mapped to the given initiator(s)."""
        if self.zapi_client.has_luns_mapped_to_initiators(initiator_list):
            return True
        if include_partner and self.partner_zapi_client and \
                self.partner_zapi_client.has_luns_mapped_to_initiators(
                    initiator_list):
            return True
        return False

    def _clone_lun(self, name, new_name, space_reserved=None,
                   qos_policy_group_name=None, src_block=0, dest_block=0,
                   block_count=0, source_snapshot=None, is_snapshot=False):
        """Clone LUN with the given handle to the new name.

        :param: is_snapshot Not used, present for method signature consistency
        """

        if not space_reserved:
            space_reserved = self.lun_space_reservation
        if qos_policy_group_name is not None:
            msg = _('Data ONTAP operating in 7-Mode does not support QoS '
                    'policy groups.')
            raise exception.VolumeDriverException(msg)

        metadata = self._get_lun_attr(name, 'metadata')
        path = metadata['Path']
        (parent, _splitter, name) = path.rpartition('/')
        clone_path = '%s/%s' % (parent, new_name)

        self.zapi_client.clone_lun(path, clone_path, name, new_name,
                                   space_reserved, src_block=src_block,
                                   dest_block=dest_block,
                                   block_count=block_count,
                                   source_snapshot=source_snapshot)

        self.vol_refresh_voluntary = True
        luns = self.zapi_client.get_lun_by_args(path=clone_path)
        cloned_lun = luns[0]
        self.zapi_client.set_space_reserve(clone_path, space_reserved)
        clone_meta = self._create_lun_meta(cloned_lun)
        handle = self._create_lun_handle(clone_meta)
        self._add_lun_to_table(
            block_base.NetAppLun(handle, new_name,
                                 cloned_lun.get_child_content('size'),
                                 clone_meta))

    def _create_lun_meta(self, lun):
        """Creates LUN metadata dictionary."""
        self.zapi_client.check_is_naelement(lun)
        meta_dict = {}
        meta_dict['Path'] = lun.get_child_content('path')
        meta_dict['Volume'] = lun.get_child_content('path').split('/')[2]
        meta_dict['OsType'] = lun.get_child_content('multiprotocol-type')
        meta_dict['SpaceReserved'] = lun.get_child_content(
            'is-space-reservation-enabled')
        meta_dict['UUID'] = lun.get_child_content('uuid')
        return meta_dict

    def _get_fc_target_wwpns(self, include_partner=True):
        wwpns = self.zapi_client.get_fc_target_wwpns()
        if include_partner and self.partner_zapi_client:
            wwpns.extend(self.partner_zapi_client.get_fc_target_wwpns())
        return wwpns

    def _update_volume_stats(self, filter_function=None,
                             goodness_function=None):
        """Retrieve stats info from filer."""

        # ensure we get current data
        self.vol_refresh_voluntary = True
        self._refresh_volume_info()

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

        self._stats = data

    def _get_pool_stats(self, filter_function=None, goodness_function=None):
        """Retrieve pool (i.e. Data ONTAP volume) stats info from volumes."""

        pools = []
        self.perf_library.update_performance_cache()

        for vol in self.vols:

            volume_name = vol.get_child_content('name')

            # omit volumes not specified in the config
            if self.volume_list and volume_name not in self.volume_list:
                continue

            # omit root volume
            if volume_name == self.root_volume_name:
                continue

            # ensure good volume state
            state = vol.get_child_content('state')
            inconsistent = vol.get_child_content('is-inconsistent')
            invalid = vol.get_child_content('is-invalid')
            if (state != 'online' or
                    inconsistent != 'false' or
                    invalid != 'false'):
                continue

            pool = dict()
            pool['pool_name'] = volume_name
            pool['QoS_support'] = False
            pool['multiattach'] = False
            pool['reserved_percentage'] = (
                self.reserved_percentage)
            pool['max_over_subscription_ratio'] = (
                self.max_over_subscription_ratio)

            # convert sizes to GB
            total = float(vol.get_child_content('size-total') or 0)
            total /= units.Gi
            pool['total_capacity_gb'] = na_utils.round_down(total, '0.01')

            free = float(vol.get_child_content('size-available') or 0)
            free /= units.Gi
            pool['free_capacity_gb'] = na_utils.round_down(free, '0.01')

            thick = (
                self.configuration.netapp_lun_space_reservation == 'enabled')
            pool['thick_provisioning_support'] = thick
            pool['thin_provisioning_support'] = not thick

            utilization = self.perf_library.get_node_utilization()
            pool['utilization'] = na_utils.round_down(utilization, '0.01')
            pool['filter_function'] = filter_function
            pool['goodness_function'] = goodness_function

            pool['consistencygroup_support'] = True

            pools.append(pool)

        return pools

    def _get_filtered_pools(self):
        """Return available pools filtered by a pool name search pattern."""

        # Inform deprecation of legacy option.
        if self.configuration.safe_get('netapp_volume_list'):
            msg = ("The option 'netapp_volume_list' is deprecated and "
                   "will be removed in the future releases. Please use "
                   "the option 'netapp_pool_name_search_pattern' instead.")
            versionutils.report_deprecated_feature(LOG, msg)

        pool_regex = na_utils.get_pool_name_filter_regex(self.configuration)

        filtered_pools = []
        for vol in self.vols:
            vol_name = vol.get_child_content('name')
            if pool_regex.match(vol_name):
                msg = ("Volume '%(vol_name)s' matches against regular "
                       "expression: %(vol_pattern)s")
                LOG.debug(msg, {'vol_name': vol_name,
                                'vol_pattern': pool_regex.pattern})
                filtered_pools.append(vol_name)
            else:
                msg = ("Volume '%(vol_name)s' does not match against regular "
                       "expression: %(vol_pattern)s")
                LOG.debug(msg, {'vol_name': vol_name,
                                'vol_pattern': pool_regex.pattern})

        return filtered_pools

    def _get_lun_block_count(self, path):
        """Gets block counts for the LUN."""
        bs = super(NetAppBlockStorage7modeLibrary,
                   self)._get_lun_block_count(path)
        api_version = self.zapi_client.get_ontapi_version()
        if api_version:
            major = api_version[0]
            minor = api_version[1]
            if major == 1 and minor < 15:
                bs -= 1
        return bs

    def _refresh_volume_info(self):
        """Saves the volume information for the filer."""

        if (self.vol_refresh_time is None or self.vol_refresh_voluntary or
                timeutils.is_newer_than(self.vol_refresh_time,
                                        self.vol_refresh_interval)):
            try:
                job_set = na_utils.set_safe_attr(self, 'vol_refresh_running',
                                                 True)
                if not job_set:
                    LOG.warning("Volume refresh job already running. "
                                "Returning...")
                    return
                self.vol_refresh_voluntary = False
                self.vols = self.zapi_client.get_filer_volumes()
                self.volume_list = self._get_filtered_pools()
                self.vol_refresh_time = timeutils.utcnow()
            except Exception as e:
                LOG.warning("Error refreshing volume info. Message: %s",
                            e)
            finally:
                na_utils.set_safe_attr(self, 'vol_refresh_running', False)

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        super(NetAppBlockStorage7modeLibrary, self).delete_volume(volume)
        self.vol_refresh_voluntary = True
        LOG.debug('Deleted LUN with name %s', volume['name'])

    def delete_snapshot(self, snapshot):
        """Driver entry point for deleting a snapshot."""
        super(NetAppBlockStorage7modeLibrary, self).delete_snapshot(snapshot)
        self.vol_refresh_voluntary = True

    def _is_lun_valid_on_storage(self, lun):
        """Validate LUN specific to storage system."""
        if self.volume_list:
            lun_vol = lun.get_metadata_property('Volume')
            if lun_vol not in self.volume_list:
                return False
        return True

    def _check_volume_type_for_lun(self, volume, lun, existing_ref,
                                   extra_specs):
        """Check if LUN satisfies volume type."""
        if extra_specs:
            legacy_policy = extra_specs.get('netapp:qos_policy_group')
            if legacy_policy is not None:
                raise exception.ManageExistingVolumeTypeMismatch(
                    reason=_("Setting LUN QoS policy group is not supported "
                             "on this storage family and ONTAP version."))
        volume_type = na_utils.get_volume_type_from_volume(volume)
        if volume_type is None:
            return
        spec = na_utils.get_backend_qos_spec_from_volume_type(volume_type)
        if spec is not None:
            raise exception.ManageExistingVolumeTypeMismatch(
                reason=_("Back-end QoS specs are not supported on this "
                         "storage family and ONTAP version."))

    def _get_preferred_target_from_list(self, target_details_list,
                                        filter=None):
        # 7-mode iSCSI LIFs migrate from controller to controller
        # in failover and flap operational state in transit, so
        # we  don't filter these on operational state.

        return (super(NetAppBlockStorage7modeLibrary, self)
                ._get_preferred_target_from_list(target_details_list))

    def _get_backing_flexvol_names(self):
        """Returns a list of backing flexvol names."""
        return self.volume_list or []

    def create_consistencygroup(self, group):
        """Driver entry point for creating a consistency group.

        ONTAP does not maintain an actual CG construct. As a result, no
        communication to the backend is necessary for consistency group
        creation.

        :returns: Hard-coded model update for consistency group model.
        """
        model_update = {'status': fields.ConsistencyGroupStatus.AVAILABLE}
        return model_update

    def delete_consistencygroup(self, group, volumes):
        """Driver entry point for deleting a consistency group.

        :returns: Updated consistency group model and list of volume models
                 for the volumes that were deleted.
        """
        model_update = {'status': fields.ConsistencyGroupStatus.DELETED}
        volumes_model_update = []
        for volume in volumes:
            try:
                self._delete_lun(volume['name'])
                volumes_model_update.append(
                    {'id': volume['id'], 'status': 'deleted'})
            except Exception:
                volumes_model_update.append(
                    {'id': volume['id'],
                     'status': 'error_deleting'})
                LOG.exception("Volume %(vol)s in the consistency group "
                              "could not be deleted.", {'vol': volume})
        return model_update, volumes_model_update

    def update_consistencygroup(self, group, add_volumes=None,
                                remove_volumes=None):
        """Driver entry point for updating a consistency group.

        Since no actual CG construct is ever created in ONTAP, it is not
        necessary to update any metadata on the backend. Since this is a NO-OP,
        there is guaranteed to be no change in any of the volumes' statuses.
        """
        return None, None, None

    def create_cgsnapshot(self, cgsnapshot, snapshots):
        """Creates a Cinder cgsnapshot object.

        The Cinder cgsnapshot object is created by making use of an
        ephemeral ONTAP CG in order to provide write-order consistency for a
        set of flexvol snapshots. First, a list of the flexvols backing the
        given Cinder CG must be gathered. An ONTAP cg-snapshot of these
        flexvols will create a snapshot copy of all the Cinder volumes in the
        CG group. For each Cinder volume in the CG, it is then necessary to
        clone its backing LUN from the ONTAP cg-snapshot. The naming convention
        used for the clones is what indicates the clone's role as a Cinder
        snapshot and its inclusion in a Cinder CG. The ONTAP CG-snapshot of
        the flexvols is no longer required after having cloned the LUNs
        backing the Cinder volumes in the Cinder CG.

        :returns: An implicit update for cgsnapshot and snapshots models that
                 is interpreted by the manager to set their models to
                 available.
        """
        flexvols = set()
        for snapshot in snapshots:
            flexvols.add(volume_utils.extract_host(snapshot['volume']['host'],
                                                   level='pool'))

        self.zapi_client.create_cg_snapshot(flexvols, cgsnapshot['id'])

        for snapshot in snapshots:
            self._clone_lun(snapshot['volume']['name'], snapshot['name'],
                            source_snapshot=cgsnapshot['id'])

        for flexvol in flexvols:
            try:
                self.zapi_client.wait_for_busy_snapshot(
                    flexvol, cgsnapshot['id'])
                self.zapi_client.delete_snapshot(
                    flexvol, cgsnapshot['id'])
            except exception.SnapshotIsBusy:
                self.zapi_client.mark_snapshot_for_deletion(
                    flexvol, cgsnapshot['id'])

        return None, None

    def delete_cgsnapshot(self, cgsnapshot, snapshots):
        """Delete LUNs backing each snapshot in the cgsnapshot.

        :returns: An implicit update for snapshots models that is interpreted
                 by the manager to set their models to deleted.
        """
        for snapshot in snapshots:
            self._delete_lun(snapshot['name'])
            LOG.debug("Snapshot %s deletion successful", snapshot['name'])

        return None, None

    def create_consistencygroup_from_src(self, group, volumes,
                                         cgsnapshot=None, snapshots=None,
                                         source_cg=None, source_vols=None):
        """Creates a CG from a either a cgsnapshot or group of cinder vols.

        :returns: An implicit update for the volumes model that is
                 interpreted by the manager as a successful operation.
        """
        LOG.debug("VOLUMES %s ", ', '.join([vol['id'] for vol in volumes]))
        volume_model_updates = []

        if cgsnapshot:
            vols = zip(volumes, snapshots)

            for volume, snapshot in vols:
                source = {
                    'name': snapshot['name'],
                    'size': snapshot['volume_size'],
                }
                volume_model_update = self._clone_source_to_destination(
                    source, volume)
                if volume_model_update is not None:
                    volume_model_update['id'] = volume['id']
                    volume_model_updates.append(volume_model_update)

        else:
            vols = zip(volumes, source_vols)

            for volume, old_src_vref in vols:
                src_lun = self._get_lun_from_table(old_src_vref['name'])
                source = {'name': src_lun.name, 'size': old_src_vref['size']}
                volume_model_update = self._clone_source_to_destination(
                    source, volume)
                if volume_model_update is not None:
                    volume_model_update['id'] = volume['id']
                    volume_model_updates.append(volume_model_update)

        return None, volume_model_updates
