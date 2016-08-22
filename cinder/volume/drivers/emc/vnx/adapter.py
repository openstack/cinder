# Copyright (c) 2016 EMC Corporation, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import json
import math
import random
import re

from oslo_log import log as logging
from oslo_utils import importutils
import six

storops = importutils.try_import('storops')
if storops:
    from storops import exception as storops_ex

from cinder import exception
from cinder.i18n import _, _LI, _LE, _LW
from cinder.objects import fields
from cinder.volume.drivers.emc.vnx import client
from cinder.volume.drivers.emc.vnx import common
from cinder.volume.drivers.emc.vnx import taskflows as emc_taskflow
from cinder.volume.drivers.emc.vnx import utils
from cinder.zonemanager import utils as zm_utils


LOG = logging.getLogger(__name__)


class CommonAdapter(object):

    VERSION = None

    def __init__(self, configuration, active_backend_id):
        self.config = configuration
        self.active_backend_id = active_backend_id
        self.client = None
        self.protocol = None
        self.serial_number = None
        self.mirror_view = None
        self.storage_pools = None
        self.max_retries = 5
        self.allowed_ports = None
        self.force_delete_lun_in_sg = None
        self.max_over_subscription_ratio = None
        self.ignore_pool_full_threshold = None
        self.reserved_percentage = None
        self.destroy_empty_sg = None
        self.itor_auto_dereg = None

    def do_setup(self):
        self._normalize_config()
        self.client = client.Client(
            self.config.san_ip,
            self.config.san_login,
            self.config.san_password,
            self.config.storage_vnx_authentication_type,
            self.config.naviseccli_path,
            self.config.storage_vnx_security_file_dir)
        # Replication related
        self.mirror_view = self.build_mirror_view(self.config, True)
        self.serial_number = self.client.get_serial()
        self.storage_pools = self.parse_pools()
        self.force_delete_lun_in_sg = (
            self.config.force_delete_lun_in_storagegroup)
        self.max_over_subscription_ratio = (
            self.config.max_over_subscription_ratio)
        self.ignore_pool_full_threshold = (
            self.config.ignore_pool_full_threshold)
        self.reserved_percentage = self.config.reserved_percentage
        self.protocol = self.config.storage_protocol
        self.destroy_empty_sg = self.config.destroy_empty_storage_group
        self.itor_auto_dereg = self.config.initiator_auto_deregistration
        self.set_extra_spec_defaults()

    def _normalize_config(self):
        # Check option `naviseccli_path`.
        # Set to None (then pass to storops) if it is not set or set to an
        # empty string.
        naviseccli_path = self.config.naviseccli_path
        if naviseccli_path is None or len(naviseccli_path.strip()) == 0:
            LOG.warning(_LW('[%(group)s] naviseccli_path is not set or set to '
                            'an empty string. None will be passed into '
                            'storops.'), {'group': self.config.config_group})
            self.config.naviseccli_path = None

        # Check option `storage_vnx_pool_names`.
        # Raise error if it is set to an empty list.
        pool_names = self.config.storage_vnx_pool_names
        if pool_names is not None:
            # Filter out the empty string in the list.
            pool_names = [name.strip()
                          for name in filter(lambda x: len(x.strip()) != 0,
                                             pool_names)]
            if len(pool_names) == 0:
                raise exception.InvalidConfigurationValue(
                    option='[{group}] storage_vnx_pool_names'.format(
                        group=self.config.config_group),
                    value=pool_names)
            self.config.storage_vnx_pool_names = pool_names

        # Check option `io_port_list`.
        # Raise error if it is set to an empty list.
        io_port_list = self.config.io_port_list
        if io_port_list is not None:
            io_port_list = [port.strip().upper()
                            for port in filter(lambda x: len(x.strip()) != 0,
                                               io_port_list)]
            if len(io_port_list) == 0:
                # io_port_list is allowed to be an empty list, which means
                # none of the ports will be registered.
                raise exception.InvalidConfigurationValue(
                    option='[{group}] io_port_list'.format(
                        group=self.config.config_group),
                    value=io_port_list)
            self.config.io_port_list = io_port_list

        if self.config.ignore_pool_full_threshold:
            LOG.warning(_LW('[%(group)s] ignore_pool_full_threshold: True. '
                            'LUN creation will still be forced even if the '
                            'pool full threshold is exceeded.'),
                        {'group': self.config.config_group})

        if self.config.destroy_empty_storage_group:
            LOG.warning(_LW('[%(group)s] destroy_empty_storage_group: True. '
                            'Empty storage group will be deleted after volume '
                            'is detached.'),
                        {'group': self.config.config_group})

        if not self.config.initiator_auto_registration:
            LOG.info(_LI('[%(group)s] initiator_auto_registration: False. '
                         'Initiator auto registration is not enabled. '
                         'Please register initiator manually.'),
                     {'group': self.config.config_group})

        if self.config.force_delete_lun_in_storagegroup:
            LOG.warning(_LW(
                '[%(group)s] force_delete_lun_in_storagegroup=True'),
                {'group': self.config.config_group})

        if self.config.ignore_pool_full_threshold:
            LOG.warning(_LW('[%(group)s] ignore_pool_full_threshold: True. '
                            'LUN creation will still be forced even if the '
                            'pool full threshold is exceeded.'),
                        {'group': self.config.config_group})

    def _build_port_str(self, port):
        raise NotImplementedError()

    def validate_ports(self, all_ports, ports_whitelist):
        # `ports_whitelist` passed the _normalize_config, then it could be only
        # None or valid list in which the items are stripped and converted to
        # upper case.
        result_ports = None
        if ports_whitelist is None:
            result_ports = all_ports
        else:
            # Split the whitelist, remove spaces around the comma,
            # and remove the empty item.
            port_strs_configed = set(ports_whitelist)
            # For iSCSI port, the format is 'A-1-1',
            # while for FC, it is 'A-2'.
            valid_port_map = {self._build_port_str(port): port
                              for port in all_ports}

            invalid_port_strs = port_strs_configed - set(valid_port_map.keys())
            if invalid_port_strs:
                msg = (_('[%(group)s] Invalid %(protocol)s ports %(port)s '
                         'specified for io_port_list.') % {
                             'group': self.config.config_group,
                             'protocol': self.config.storage_protocol,
                             'port': ','.join(invalid_port_strs)})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            result_ports = [valid_port_map[port_str]
                            for port_str in port_strs_configed]

        if not result_ports:
            raise exception.VolumeBackendAPIException(
                data=_('No valid ports.'))
        return result_ports

    def set_extra_spec_defaults(self):
        provision_default = storops.VNXProvisionEnum.THICK
        tier_default = None
        if self.client.is_fast_enabled():
            tier_default = storops.VNXTieringEnum.HIGH_AUTO
        common.ExtraSpecs.set_defaults(provision_default, tier_default)

    def create_volume(self, volume):
        """Creates a EMC volume."""
        volume_size = volume['size']
        volume_name = volume['name']

        volume_metadata = utils.get_metadata(volume)
        pool = utils.get_pool_from_host(volume.host)
        specs = common.ExtraSpecs.from_volume(volume)

        provision = specs.provision
        tier = specs.tier

        volume_metadata['snapcopy'] = 'False'
        LOG.info(_LI('Create Volume: %(volume)s  Size: %(size)s '
                     'pool: %(pool)s '
                     'provision: %(provision)s '
                     'tier: %(tier)s '),
                 {'volume': volume_name,
                  'size': volume_size,
                  'pool': pool,
                  'provision': provision,
                  'tier': tier})

        lun = self.client.create_lun(
            pool, volume_name, volume_size,
            provision, tier, volume.consistencygroup_id,
            ignore_thresholds=self.config.ignore_pool_full_threshold)
        location = self._build_provider_location(
            lun_type='lun',
            lun_id=lun.lun_id,
            base_lun_name=volume.name)
        # Setup LUN Replication/MirrorView between devices.
        # Secondary LUN will inherit properties from primary LUN.
        rep_update = self.setup_lun_replication(
            volume, lun.lun_id)
        model_update = {'provider_location': location,
                        'metadata': volume_metadata}
        model_update.update(rep_update)
        return model_update

    def retype(self, ctxt, volume, new_type, diff, host):
        """Changes volume from one type to another."""
        new_specs = common.ExtraSpecs.from_volume_type(new_type)
        new_specs.validate(self.client.get_vnx_enabler_status())
        lun = self.client.get_lun(name=volume.name)
        if volume.volume_type_id:
            old_specs = common.ExtraSpecs.from_volume(volume)
        else:
            # Get extra specs from the LUN properties when the lun
            # has no volume type.
            utils.update_res_without_poll(lun)
            old_specs = common.ExtraSpecs.from_lun(lun)
        old_provision = old_specs.provision
        old_tier = old_specs.tier
        need_migration = utils.retype_need_migration(
            volume, old_provision, new_specs.provision, host)
        turn_on_compress = utils.retype_need_turn_on_compression(
            old_provision, new_specs.provision)
        change_tier = utils.retype_need_change_tier(
            old_tier, new_specs.tier)

        if need_migration or turn_on_compress:
            if self.client.lun_has_snapshot(lun):
                LOG.debug('Driver is not able to do retype because the volume '
                          '%s has a snapshot.',
                          volume.id)
                return False

        if need_migration:
            LOG.debug('Driver needs to use storage-assisted migration '
                      'to retype the volume.')
            return self._migrate_volume(volume, host, new_specs)
        if turn_on_compress:
            # Turn on compression feature on the volume
            self.client.enable_compression(lun)
        if change_tier:
            # Modify lun to change tiering policy
            lun.tier = new_specs.tier
        return True

    def create_volume_from_snapshot(self, volume, snapshot):
        """Constructs a work flow to create a volume from snapshot.

        :param volume: new volume
        :param snapshot: base snapshot
        This flow will do the following:

        1. Create a snap mount point (SMP) for the snapshot.
        2. Attach the snapshot to the SMP created in the first step.
        3. Create a temporary lun prepare for migration.
           (Skipped if snapcopy='true')
        4. Start a migration between the SMP and the temp lun.
           (Skipped if snapcopy='true')
        """
        volume_metadata = utils.get_metadata(volume)
        pool = utils.get_pool_from_host(volume.host)

        specs = common.ExtraSpecs.from_volume(volume)
        provision = specs.provision
        tier = specs.tier
        base_lun_name = utils.get_base_lun_name(snapshot.volume)
        rep_update = dict()
        if utils.snapcopy_enabled(volume):
            new_lun_id = emc_taskflow.fast_create_volume_from_snapshot(
                client=self.client,
                snap_name=snapshot.name,
                new_snap_name=utils.construct_snap_name(volume),
                lun_name=volume.name,
                base_lun_name=base_lun_name,
                pool_name=pool)
            location = self._build_provider_location(
                lun_type='smp',
                lun_id=new_lun_id,
                base_lun_name=base_lun_name)
            volume_metadata['snapcopy'] = 'True'
        else:
            new_lun_id = emc_taskflow.create_volume_from_snapshot(
                client=self.client,
                snap_name=snapshot.name,
                lun_name=volume.name,
                lun_size=volume.size,
                base_lun_name=base_lun_name,
                pool_name=pool,
                provision=provision,
                tier=tier)
            location = self._build_provider_location(
                lun_type='lun',
                lun_id=new_lun_id,
                base_lun_name=volume.name)
            volume_metadata['snapcopy'] = 'False'
            rep_update = self.setup_lun_replication(volume, new_lun_id)

        model_update = {'provider_location': location,
                        'metadata': volume_metadata}
        model_update.update(rep_update)
        return model_update

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        volume_metadata = utils.get_metadata(volume)
        pool = utils.get_pool_from_host(volume.host)

        specs = common.ExtraSpecs.from_volume(volume)
        provision = specs.provision
        tier = specs.tier
        base_lun_name = utils.get_base_lun_name(src_vref)

        source_lun_id = self.client.get_lun_id(src_vref)
        snap_name = utils.construct_snap_name(volume)
        rep_update = dict()
        if utils.snapcopy_enabled(volume):
            # snapcopy feature enabled
            new_lun_id = emc_taskflow.fast_create_cloned_volume(
                client=self.client,
                snap_name=snap_name,
                lun_id=source_lun_id,
                lun_name=volume.name,
                base_lun_name=base_lun_name
            )
            location = self._build_provider_location(
                lun_type='smp',
                lun_id=new_lun_id,
                base_lun_name=base_lun_name)
        else:
            new_lun_id = emc_taskflow.create_cloned_volume(
                client=self.client,
                snap_name=snap_name,
                lun_id=source_lun_id,
                lun_name=volume.name,
                lun_size=volume.size,
                base_lun_name=base_lun_name,
                pool_name=pool,
                provision=provision,
                tier=tier)
            self.client.delete_snapshot(snap_name)
            # After migration, volume's base lun is itself
            location = self._build_provider_location(
                lun_type='lun',
                lun_id=new_lun_id,
                base_lun_name=volume.name)
            volume_metadata['snapcopy'] = 'False'
            rep_update = self.setup_lun_replication(volume, new_lun_id)

        model_update = {'provider_location': location,
                        'metadata': volume_metadata}
        model_update.update(rep_update)
        return model_update

    def migrate_volume(self, context, volume, host):
        """Leverage the VNX on-array migration functionality.

        This method is invoked at the source backend.
        """
        specs = common.ExtraSpecs.from_volume(volume)
        return self._migrate_volume(volume, host, specs)

    def _migrate_volume(self, volume, host, extra_specs):
        """Migrates volume.

        :param extra_specs: Instance of ExtraSpecs. The new volume will be
            changed to align with the new extra specs.
        """
        r = utils.validate_storage_migration(
            volume, host, self.serial_number, self.protocol)
        if not r:
            return r, None
        rate = utils.get_migration_rate(volume)

        new_pool = utils.get_pool_from_host(host['host'])
        lun_id = self.client.get_lun_id(volume)
        lun_name = volume.name
        provision = extra_specs.provision
        tier = extra_specs.tier

        emc_taskflow.run_migration_taskflow(
            self.client, lun_id, lun_name, volume.size,
            new_pool, provision, tier, rate)

        # A smp will become a LUN after migration
        if utils.is_volume_smp(volume):
            self.client.delete_snapshot(
                utils.construct_snap_name(volume))
        volume_metadata = utils.get_metadata(volume)
        pl = self._build_provider_location(
            lun_type='lun',
            lun_id=lun_id,
            base_lun_name=volume.name)
        volume_metadata['snapcopy'] = 'False'
        model_update = {'provider_location': pl,
                        'metadata': volume_metadata}
        return True, model_update

    def create_consistencygroup(self, context, group):
        cg_name = group.id
        utils.validate_cg_type(group)
        model_update = {'status': fields.ConsistencyGroupStatus.AVAILABLE}
        self.client.create_consistency_group(cg_name=cg_name)
        return model_update

    def delete_consistencygroup(self, context, group, volumes):
        """Deletes a consistency group."""
        cg_name = group.id

        model_update = {}
        volumes_model_update = []
        model_update['status'] = group.status
        LOG.info(_LI('Start to delete consistency group: %(cg_name)s'),
                 {'cg_name': cg_name})

        self.client.delete_consistency_group(cg_name)

        for volume in volumes:
            try:
                self.client.delete_lun(volume.name)
                volumes_model_update.append(
                    {'id': volume.id,
                     'status': fields.ConsistencyGroupStatus.DELETED})
            except storops_ex.VNXDeleteLunError:
                volumes_model_update.append(
                    {'id': volume.id,
                     'status': fields.ConsistencyGroupStatus.ERROR_DELETING})

        return model_update, volumes_model_update

    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Creates a CG snapshot(snap group)."""
        model_update = {}
        snapshots_model_update = []
        LOG.info(_LI('Creating CG snapshot for consistency group'
                     ': %(group_name)s'),
                 {'group_name': cgsnapshot.consistencygroup_id})

        self.client.create_cg_snapshot(cgsnapshot.id,
                                       cgsnapshot.consistencygroup_id)
        for snapshot in snapshots:
            snapshots_model_update.append(
                {'id': snapshot.id, 'status': 'available'})
        model_update['status'] = 'available'

        return model_update, snapshots_model_update

    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Deletes a CG snapshot(snap group)."""
        model_update = {}
        snapshots_model_update = []
        model_update['status'] = cgsnapshot.status
        LOG.info(_LI('Deleting CG snapshot %(snap_name)s for consistency '
                     'group: %(group_name)s'),
                 {'snap_name': cgsnapshot.id,
                  'group_name': cgsnapshot.consistencygroup_id})

        self.client.delete_cg_snapshot(cgsnapshot.id)
        for snapshot in snapshots:
            snapshots_model_update.append(
                {'id': snapshot.id, 'status': 'deleted'})
        model_update['status'] = 'deleted'

        return model_update, snapshots_model_update

    def create_cg_from_cgsnapshot(self, context, group,
                                  volumes, cgsnapshot, snapshots):
        # 1. Copy a temp CG snapshot from CG snapshot
        #    and allow RW for it
        # 2. Create SMPs from source volumes
        # 3. Attach SMPs to the CG snapshot
        # 4. Create migration target LUNs
        # 5. Migrate from SMPs to LUNs one by one
        # 6. Wait completion of migration
        # 7. Create a new CG, add all LUNs to it
        # 8. Delete the temp CG snapshot
        cg_name = group.id
        src_cg_snap_name = cgsnapshot.id
        pool_name = utils.get_pool_from_host(group.host)
        lun_sizes = []
        lun_names = []
        src_lun_names = []
        specs_list = []
        for volume, snapshot in zip(volumes, snapshots):
            lun_sizes.append(volume.size)
            lun_names.append(volume.name)
            src_lun_names.append(snapshot.volume.name)
            specs_list.append(common.ExtraSpecs.from_volume(volume))

        lun_id_list = emc_taskflow.create_cg_from_cg_snapshot(
            client=self.client,
            cg_name=cg_name,
            src_cg_name=None,
            cg_snap_name=None,
            src_cg_snap_name=src_cg_snap_name,
            pool_name=pool_name,
            lun_sizes=lun_sizes,
            lun_names=lun_names,
            src_lun_names=src_lun_names,
            specs_list=specs_list)

        volume_model_updates = []
        for volume, lun_id in zip(volumes, lun_id_list):
            model_update = {
                'id': volume.id,
                'provider_location':
                    self._build_provider_location(
                        lun_id=lun_id,
                        lun_type='lun',
                        base_lun_name=volume.name
                    )}
            volume_model_updates.append(model_update)
        return None, volume_model_updates

    def create_cloned_cg(self, context, group,
                         volumes, source_cg, source_vols):
        # 1. Create temp CG snapshot from source_cg
        # Same with steps 2-8 of create_cg_from_cgsnapshot
        pool_name = utils.get_pool_from_host(group.host)
        lun_sizes = []
        lun_names = []
        src_lun_names = []
        specs_list = []
        for volume, source_vol in zip(volumes, source_vols):
            lun_sizes.append(volume.size)
            lun_names.append(volume.name)
            src_lun_names.append(source_vol.name)
            specs_list.append(common.ExtraSpecs.from_volume(volume))

        lun_id_list = emc_taskflow.create_cloned_cg(
            client=self.client,
            cg_name=group.id,
            src_cg_name=source_cg.id,
            pool_name=pool_name,
            lun_sizes=lun_sizes,
            lun_names=lun_names,
            src_lun_names=src_lun_names,
            specs_list=specs_list)

        volume_model_updates = []
        for volume, lun_id in zip(volumes, lun_id_list):
            model_update = {
                'id': volume.id,
                'provider_location':
                    self._build_provider_location(
                        lun_id=lun_id,
                        lun_type='lun',
                        base_lun_name=volume.name
                    )}
            volume_model_updates.append(model_update)
        return None, volume_model_updates

    def parse_pools(self):
        pool_names = self.config.storage_vnx_pool_names
        array_pools = self.client.get_pools()
        if pool_names:
            pool_names = set([po.strip() for po in pool_names])
            array_pool_names = set([po.name for po in array_pools])
            nonexistent_pools = pool_names.difference(array_pool_names)
            pool_names.difference_update(nonexistent_pools)
            if not pool_names:
                msg = _('All the specified storage pools to be managed '
                        'do not exist. Please check your configuration. '
                        'Non-existent pools: %s') % ','.join(nonexistent_pools)
                raise exception.VolumeBackendAPIException(data=msg)
            if nonexistent_pools:
                LOG.warning(_LW('The following specified storage pools '
                                'do not exist: %(nonexistent)s. '
                                'This host will only manage the storage '
                                'pools: %(exist)s'),
                            {'nonexistent': ','.join(nonexistent_pools),
                             'exist': ','.join(pool_names)})
            else:
                LOG.debug('This host will manage the storage pools: %s.',
                          ','.join(pool_names))
        else:
            pool_names = [p.name for p in array_pools]
            LOG.info(_LI('No storage pool is configured. This host will '
                         'manage all the pools on the VNX system.'))

        return list(filter(lambda pool: pool.name in pool_names, array_pools))

    def get_enabler_stats(self):
        stats = dict()
        stats['compression_support'] = self.client.is_compression_enabled()
        stats['fast_support'] = self.client.is_fast_enabled()
        stats['deduplication_support'] = self.client.is_dedup_enabled()
        stats['thin_provisioning_support'] = self.client.is_thin_enabled()
        stats['consistencygroup_support'] = self.client.is_snap_enabled()
        stats['replication_enabled'] = True if self.mirror_view else False
        return stats

    def get_pool_stats(self, enabler_stats=None):
        stats = enabler_stats if enabler_stats else self.get_enabler_stats()
        self.storage_pools = self.parse_pools()
        pool_feature = self.client.get_pool_feature()
        pools_stats = list()
        for pool in self.storage_pools:
            pool_stats = {
                'pool_name': pool.name,
                'total_capacity_gb': pool.user_capacity_gbs,
                'provisioned_capacity_gb': pool.total_subscribed_capacity_gbs
            }

            # Handle pool state Initializing, Ready, Faulted, Offline
            # or Deleting.
            if pool.state in common.PoolState.VALID_CREATE_LUN_STATE:
                pool_stats['free_capacity_gb'] = 0
                LOG.warning(_LW('Storage Pool [%(pool)s] is [%(state)s].'),
                            {'pool': pool.name,
                             'state': pool.state})
            else:
                pool_stats['free_capacity_gb'] = pool.available_capacity_gbs

                if (pool_feature.max_pool_luns <=
                        pool_feature.total_pool_luns):
                    LOG.warning(_LW('Maximum number of Pool LUNs %(max_luns)s '
                                    'have been created for %(pool_name)s. '
                                    'No more LUN creation can be done.'),
                                {'max_luns': pool_feature.max_pool_luns,
                                 'pool_name': pool.name})
                    pool_stats['free_capacity_gb'] = 0

            if not self.reserved_percentage:
                # Since the admin is not sure of what value is proper,
                # the driver will calculate the recommended value.

                # Some extra capacity will be used by meta data of pool LUNs.
                # The overhead is about LUN_Capacity * 0.02 + 3 GB
                # reserved_percentage will be used to make sure the scheduler
                # takes the overhead into consideration.
                # Assume that all the remaining capacity is to be used to
                # create a thick LUN, reserved_percentage is estimated as
                # follows:
                reserved = (((0.02 * pool.available_capacity_gbs + 3) /
                             (1.02 * pool.user_capacity_gbs)) * 100)
                # Take pool full threshold into consideration
                if not self.ignore_pool_full_threshold:
                    reserved += 100 - pool.percent_full_threshold
                pool_stats['reserved_percentage'] = int(math.ceil(min(reserved,
                                                                      100)))
            else:
                pool_stats['reserved_percentage'] = self.reserved_percentage

            array_serial = self.serial_number
            pool_stats['location_info'] = ('%(pool_name)s|%(array_serial)s' %
                                           {'pool_name': pool.name,
                                            'array_serial': array_serial})
            pool_stats['fast_cache_enabled'] = pool.fast_cache

            # Copy advanced feature stats from backend stats
            pool_stats['compression_support'] = stats['compression_support']
            pool_stats['fast_support'] = stats['fast_support']
            pool_stats['deduplication_support'] = (
                stats['deduplication_support'])
            pool_stats['thin_provisioning_support'] = (
                stats['thin_provisioning_support'])
            pool_stats['thick_provisioning_support'] = True
            pool_stats['consistencygroup_support'] = (
                stats['consistencygroup_support'])
            pool_stats['max_over_subscription_ratio'] = (
                self.max_over_subscription_ratio)
            # Add replication v2.1 support
            self.append_replication_stats(pool_stats)
            pools_stats.append(pool_stats)
        return pools_stats

    def append_replication_stats(self, stats):
        if self.mirror_view:
            stats['replication_enabled'] = True
            stats['replication_count'] = 1
            stats['replication_type'] = ['sync']
        else:
            stats['replication_enabled'] = False
        stats['replication_targets'] = [
            device.backend_id for device in common.ReplicationDeviceList(
                self.config)]

    def update_volume_stats(self):
        stats = self.get_enabler_stats()
        stats['pools'] = self.get_pool_stats(stats)
        stats['storage_protocol'] = self.config.storage_protocol
        self.append_replication_stats(stats)
        return stats

    def delete_volume(self, volume):
        """Deletes an EMC volume."""
        self.cleanup_lun_replication(volume)
        self.client.delete_lun(volume.name, force=self.force_delete_lun_in_sg)

    def extend_volume(self, volume, new_size):
        """Extends an EMC volume."""
        self.client.expand_lun(volume.name, new_size, poll=False)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        src_lun_id = self.client.get_lun_id(snapshot.volume)
        self.client.create_snapshot(src_lun_id, snapshot.name)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self.client.delete_snapshot(snapshot.name)

    def _get_referenced_lun(self, existing_ref):
        lun = None
        if 'source-id' in existing_ref:
            lun = self.client.get_lun(lun_id=existing_ref['source-id'])
        elif 'source-name' in existing_ref:
            lun = self.client.get_lun(name=existing_ref['source-name'])
        else:
            reason = _('Reference must contain source-id or source-name key.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        if not lun.existed:
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=_("LUN doesn't exist."))
        return lun

    def manage_existing_get_size(self, volume, existing_ref):
        """Returns size of volume to be managed by manage_existing."""
        lun = self._get_referenced_lun(existing_ref)
        target_pool = utils.get_pool_from_host(volume.host)
        if target_pool and lun.pool_name != target_pool:
            reason = (_('The imported lun is in pool %(lun_pool)s '
                        'which is not managed by the host %(host)s.')
                      % {'lun_pool': lun.pool_name,
                         'host': volume['host']})
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        return lun.total_capacity_gb

    def manage_existing(self, volume, existing_ref):
        """Imports the existing backend storage object as a volume.

        manage_existing_ref:{
            'source-id':<lun id in VNX>
        }
        or
        manage_existing_ref:{
            'source-name':<lun name in VNX>
        }

        When the volume has a volume_type, the driver inspects that and
        compare against the properties of the referenced backend storage
        object.  If they are incompatible, raise a
        ManageExistingVolumeTypeMismatch exception.
        """
        lun = self._get_referenced_lun(existing_ref)
        if volume.volume_type_id:
            type_specs = common.ExtraSpecs.from_volume(volume)
            if not type_specs.match_with_lun(lun):
                raise exception.ManageExistingVolumeTypeMismatch(
                    reason=_("The volume to be managed is a %(provision)s LUN "
                             "and the tiering setting is %(tier)s. This "
                             "doesn't match with the type %(type)s.")
                    % {'provision': lun.provision,
                       'tier': lun.tier,
                       'type': volume.volume_type_id})
        lun.rename(volume.name)
        if lun.is_snap_mount_point:
            lun_type = 'smp'
            base_lun_name = lun.primary_lun
        else:
            lun_type = 'lun'
            base_lun_name = volume.name
        pl = self._build_provider_location(
            lun_id=lun.lun_id,
            lun_type=lun_type,
            base_lun_name=base_lun_name)
        return {'provider_location': pl}

    def unmanage(self, volume):
        """Unmanages a volume."""
        pass

    def build_host(self, connector):
        raise NotImplementedError

    def assure_storage_group(self, host):
        """Assures that the storage group with name of `host` exists.

        If the storage group doesn't exist, create a one.
        """
        sg = self.client.get_storage_group(host.name)
        is_new_sg = False
        if not sg.existed:
            sg = self.client.create_storage_group(host.name)
            is_new_sg = True
        return (sg, is_new_sg)

    def assure_host_access(self, storage_group, host, volume, is_new_sg):
        """Assures that `host` is connected to the Array.

        It first registers initiators to `storage_group` then add `volume` to
        `storage_group`.

        :param storage_group: object of storops storage group to which the
                              host access is registered.
        :param host: `common.Host` object with initiator information.
        :param volume: `common.Volume` object with volume information.
        :param is_new_sg: flag indicating whether the `storage_group` is newly
                          created or not.
        """
        if not self.config.initiator_auto_registration:
            if is_new_sg:
                # Invoke connect_host on storage group to register all
                # host information.
                # Call connect_host only once when sg is newly created.
                storage_group.connect_host(host.name)
        else:
            self.auto_register_initiator(storage_group, host)

        return self.client.add_lun_to_sg(
            storage_group,
            self.client.get_lun(lun_id=volume.vnx_lun_id),
            self.max_retries)

    def auto_register_initiator(self, storage_group, host):
        """Registers the initiators to storage group.

        :param storage_group: storage group object to which the initiator is
                              registered.
        :param host: information of initiator, etc.

        The behavior depends on the combination of the registered
        initiators of SG and the configured white list of the ports (that is
        `self.config.io_port_list`).

        1. Register all non-registered initiators to `self.allowed_ports`.
        2. For registered initiators, if the white list is configured, register
        them to `self.allowed_ports` except the ones which are already
        registered.
        Note that `self.allowed_ports` comprises of all iSCSI/FC ports on array
        or the valid ports of the white list if `self.config.io_port_list` is
        configured.
        """

        host_initiators = set(host.initiators)
        sg_initiators = set(storage_group.initiator_uid_list)
        unreg_initiators = host_initiators - sg_initiators
        initiator_port_map = {unreg_id: set(self.allowed_ports)
                              for unreg_id in unreg_initiators}

        if self.config.io_port_list is not None:
            reg_initiators = host_initiators & sg_initiators
            for reg_id in reg_initiators:
                ports_to_reg = (set(self.allowed_ports) -
                                set(storage_group.get_ports(reg_id)))
                if ports_to_reg:
                    initiator_port_map[reg_id] = ports_to_reg
                    LOG.debug('Ports [%(ports)s] in white list will be bound '
                              'to the registered initiator: %(reg_id)s',
                              {'ports': ports_to_reg, 'reg_id': reg_id})

        self.client.register_initiator(storage_group, host, initiator_port_map)

    def prepare_target_data(self, storage_group, host, volume, hlu):
        raise NotImplementedError()

    def initialize_connection(self, cinder_volume, connector):
        """Initializes the connection to `cinder_volume`."""
        volume = common.Volume(
            cinder_volume.name, cinder_volume.id,
            vnx_lun_id=self.client.get_lun_id(cinder_volume))
        return self._initialize_connection(volume, connector)

    def _initialize_connection(self, volume, connector):
        """Helps to initialize the connection.

        To share common codes with initialize_connection_snapshot.

        :param volume: `common.Volume` object with volume information.
        :param connector: connector information from Nova.
        """
        host = self.build_host(connector)
        sg, is_new_sg = self.assure_storage_group(host)
        hlu = self.assure_host_access(sg, host, volume, is_new_sg)
        return self.prepare_target_data(sg, host, volume, hlu)

    def terminate_connection(self, cinder_volume, connector):
        """Terminates the connection to `cinder_volume`."""
        volume = common.Volume(
            cinder_volume.name, cinder_volume.id,
            vnx_lun_id=self.client.get_lun_id(cinder_volume))
        return self._terminate_connection(volume, connector)

    def _terminate_connection(self, volume, connector):
        """Helps to terminate the connection.

        To share common codes with terminate_connection_snapshot.

        :param volume: `common.Volume` object with volume information.
        :param connector: connector information from Nova.
        """
        host = self.build_host(connector)
        sg = self.client.get_storage_group(host.name)
        self.remove_host_access(volume, host, sg)

        # build_terminate_connection return data should go before
        # terminate_connection_cleanup. The storage group may be deleted in
        # the terminate_connection_cleanup which is needed during getting
        # return data
        self.update_storage_group_if_required(sg)
        re = self.build_terminate_connection_return_data(host, sg)
        self.terminate_connection_cleanup(host, sg)

        return re

    def update_storage_group_if_required(self, sg):
        if sg.existed and self.destroy_empty_sg:
            utils.update_res_with_poll(sg)

    def remove_host_access(self, volume, host, sg):
        """Removes the host access from `volume`.

        :param volume: `common.Volume` object with volume information.
        :param host: `common.Host` object with host information.
        :param sg: object of `storops` storage group.
        """
        lun = self.client.get_lun(lun_id=volume.vnx_lun_id)
        hostname = host.name
        if not sg.existed:
            LOG.warning(_LW("Storage Group %s is not found. "
                            "Nothing can be done in terminate_connection()."),
                        hostname)
        else:
            try:
                sg.detach_alu(lun)
            except storops_ex.VNXDetachAluNotFoundError:
                LOG.warning(_LW("Volume %(vol)s is not in Storage Group"
                                " %(sg)s."),
                            {'vol': volume.name, 'sg': hostname})

    def build_terminate_connection_return_data(self, host, sg):
        raise NotImplementedError()

    def terminate_connection_cleanup(self, host, sg):
        if not sg.existed:
            return

        if self.destroy_empty_sg:
            if not self.client.sg_has_lun_attached(sg):
                self._destroy_empty_sg(host, sg)

    def _destroy_empty_sg(self, host, sg):
        try:
            LOG.info(_LI("Storage Group %s is empty."), sg.name)
            sg.disconnect_host(sg.name)
            sg.remove()
            if self.itor_auto_dereg:
                self._deregister_initiator(host)
        except storops_ex.StoropsException:
            LOG.warning(_LW("Failed to destroy Storage Group %s."),
                        sg.name)
            try:
                sg.connect_host(sg.name)
            except storops_ex.StoropsException:
                LOG.warning(_LW("Failed to connect host %(host)s "
                                "back to storage group %(sg)s."),
                            {'host': sg.name, 'sg': sg.name})

    def _deregister_initiator(self, host):
        initiators = host.initiators
        try:
            self.client.deregister_initiators(initiators)
        except storops_ex:
            LOG.warning(_LW("Failed to deregister the initiators %s"),
                        initiators)

    def _is_allowed_port(self, port):
        return port in self.allowed_ports

    def _build_provider_location(
            self, lun_id=None, lun_type=None, base_lun_name=None):
        return utils.build_provider_location(
            system=self.serial_number,
            lun_type=lun_type,
            lun_id=lun_id,
            base_lun_name=base_lun_name,
            version=self.VERSION)

    def update_consistencygroup(self, context, group, add_volumes,
                                remove_volumes):
        cg = self.client.get_cg(name=group.id)
        lun_ids_to_add = [self.client.get_lun_id(volume)
                          for volume in add_volumes]
        lun_ids_to_remove = [self.client.get_lun_id(volume)
                             for volume in remove_volumes]
        self.client.update_consistencygroup(cg, lun_ids_to_add,
                                            lun_ids_to_remove)
        return ({'status': fields.ConsistencyGroupStatus.AVAILABLE},
                None,
                None)

    def create_export_snapshot(self, context, snapshot, connector):
        self.client.create_mount_point(snapshot.volume_name,
                                       utils.construct_smp_name(snapshot.id))

    def remove_export_snapshot(self, context, snapshot):
        self.client.delete_lun(utils.construct_smp_name(snapshot.id))

    def initialize_connection_snapshot(self, snapshot, connector, **kwargs):
        """Initializes connection for snapshot mount point."""
        smp_name = utils.construct_smp_name(snapshot.id)
        self.client.attach_snapshot(smp_name, snapshot.name)
        lun = self.client.get_lun(name=smp_name)
        volume = common.Volume(smp_name, snapshot.id, vnx_lun_id=lun.lun_id)
        self._initialize_connection(volume, connector)

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        """Terminates connection for snapshot mount point."""
        smp_name = utils.construct_smp_name(snapshot.id)
        lun = self.client.get_lun(name=smp_name)
        volume = common.Volume(smp_name, snapshot.id, vnx_lun_id=lun.lun_id)
        connection_info = self._terminate_connection(volume, connector)
        self.client.detach_snapshot(smp_name)
        return connection_info

    def setup_lun_replication(self, volume, primary_lun_id):
        """Setup replication for LUN, this only happens in primary system."""
        specs = common.ExtraSpecs.from_volume(volume)
        provision = specs.provision
        tier = specs.tier
        rep_update = {'replication_driver_data': None,
                      'replication_status': fields.ReplicationStatus.DISABLED}
        if specs.is_replication_enabled:
            LOG.debug('Starting setup replication '
                      'for volume: %s.', volume.id)
            lun_size = volume.size
            mirror_name = utils.construct_mirror_name(volume)
            pool_name = utils.get_pool_from_host(volume.host)
            emc_taskflow.create_mirror_view(
                self.mirror_view, mirror_name,
                primary_lun_id, pool_name,
                volume.name, lun_size,
                provision, tier)

            LOG.info(_LI('Successfully setup replication for %s.'), volume.id)
            rep_update.update({'replication_status':
                               fields.ReplicationStatus.ENABLED})
        return rep_update

    def cleanup_lun_replication(self, volume):
        specs = common.ExtraSpecs.from_volume(volume)
        if specs.is_replication_enabled:
            LOG.debug('Starting cleanup replication from volume: '
                      '%s.', volume.id)
            mirror_name = utils.construct_mirror_name(volume)
            mirror_view = self.build_mirror_view(self.config, True)
            mirror_view.destroy_mirror(mirror_name, volume.name)
            LOG.info(
                _LI('Successfully destroyed replication for volume: %s'),
                volume.id)

    def build_mirror_view(self, configuration, failover=True):
        """Builds a mirror view operation class.

        :param configuration: driver configuration
        :param failover: True if from primary to configured array,
        False if from configured array to primary.
        """
        rep_devices = configuration.replication_device
        if not rep_devices:
            LOG.info(_LI('Replication is not configured on backend: %s.'),
                     configuration.config_group)
            return None
        elif len(rep_devices) == 1:
            if not self.client.is_mirror_view_enabled():
                error_msg = _('Replication is configured, '
                              'but no MirrorView/S enabler installed on VNX.')
                raise exception.InvalidInput(reason=error_msg)
            rep_list = common.ReplicationDeviceList(configuration)
            device = rep_list[0]
            secondary_client = client.Client(
                ip=device.san_ip,
                username=device.san_login,
                password=device.san_password,
                scope=device.storage_vnx_authentication_type,
                naviseccli=self.client.naviseccli,
                sec_file=device.storage_vnx_security_file_dir)
            if failover:
                mirror_view = common.VNXMirrorView(
                    self.client, secondary_client)
            else:
                # For fail-back, we need to take care of reversed ownership.
                mirror_view = common.VNXMirrorView(
                    secondary_client, self.client)
            return mirror_view
        else:
            error_msg = _('VNX Cinder driver does not support '
                          'multiple replication targets.')
            raise exception.InvalidInput(reason=error_msg)

    def validate_backend_id(self, backend_id):
        # Currently, VNX driver only support 1 remote device.
        replication_device = common.ReplicationDeviceList(self.config)[0]
        if backend_id not in (
                'default', replication_device.backend_id):
            raise exception.InvalidInput(
                reason='Invalid backend_id specified.')

    def failover_host(self, context, volumes, secondary_backend_id):
        """Fails over the volume back and forth.

        Driver needs to update following info for failed-over volume:
        1. provider_location: update serial number and lun id
        2. replication_status: new status for replication-enabled volume
        """
        volume_update_list = []
        self.validate_backend_id(secondary_backend_id)
        if secondary_backend_id != 'default':
            rep_status = fields.ReplicationStatus.FAILED_OVER
            mirror_view = self.build_mirror_view(self.config, True)
        else:
            rep_status = fields.ReplicationStatus.ENABLED
            mirror_view = self.build_mirror_view(self.config, False)

        def failover_volume(volume, new_status):
            mirror_name = utils.construct_mirror_name(volume)

            provider_location = volume.provider_location
            try:
                mirror_view.promote_image(mirror_name)
            except storops_ex.VNXMirrorException as ex:
                msg = _LE(
                    'Failed to failover volume %(volume_id)s '
                    'to %(target)s: %(error)s.')
                LOG.error(msg, {'volume_id': volume.id,
                                'target': secondary_backend_id,
                                'error': ex},)
                new_status = fields.ReplicationStatus.ERROR
            else:
                # Transfer ownership to secondary_backend_id and
                # update provider_location field
                secondary_client = mirror_view.secondary_client
                updated = dict()
                updated['system'] = secondary_client.get_serial()
                updated['id'] = six.text_type(
                    secondary_client.get_lun(name=volume.name).lun_id)
                provider_location = utils.update_provider_location(
                    provider_location, updated)
            model_update = {'volume_id': volume.id,
                            'updates':
                                {'replication_status': new_status,
                                 'provider_location': provider_location}}
            volume_update_list.append(model_update)
        for volume in volumes:
            specs = common.ExtraSpecs.from_volume(volume)
            if specs.is_replication_enabled:
                failover_volume(volume, rep_status)
            else:
                # Since the array has been failed-over
                # volumes without replication should be in error.
                volume_update_list.append({
                    'volume_id': volume.id,
                    'updates': {'status': 'error'}})
        return secondary_backend_id, volume_update_list

    def get_pool_name(self, volume):
        return self.client.get_pool_name(volume.name)

    def update_migrated_volume(self, context, volume, new_volume,
                               original_volume_status=None):
        """Updates metadata after host-assisted migration."""
        metadata = utils.get_metadata(volume)
        metadata['snapcopy'] = ('True' if utils.is_volume_smp(new_volume)
                                else 'False')
        return {'provider_location': new_volume.provider_location,
                'metadata': metadata}


class ISCSIAdapter(CommonAdapter):
    def __init__(self, configuration, active_backend_id):
        super(ISCSIAdapter, self).__init__(configuration, active_backend_id)
        self.iscsi_initiator_map = None

    def do_setup(self):
        super(ISCSIAdapter, self).do_setup()

        self.iscsi_initiator_map = self.config.iscsi_initiators
        self.allowed_ports = self.validate_ports(
            self.client.get_iscsi_targets(),
            self.config.io_port_list)
        LOG.debug('[%(group)s] allowed_ports are: [%(ports)s].',
                  {'group': self.config.config_group,
                   'ports': ','.join(
                       [port.display_name for port in self.allowed_ports])})

    def _normalize_config(self):
        super(ISCSIAdapter, self)._normalize_config()

        # Check option `iscsi_initiators`.
        # Set to None if it is not set or set to an empty string.
        # Raise error if it is set to an empty string.
        iscsi_initiators = self.config.iscsi_initiators
        option = '[{group}] iscsi_initiators'.format(
            group=self.config.config_group)
        if iscsi_initiators is None:
            return
        elif len(iscsi_initiators.strip()) == 0:
            raise exception.InvalidConfigurationValue(option=option,
                                                      value=iscsi_initiators)
        else:
            try:
                self.config.iscsi_initiators = json.loads(iscsi_initiators)
            except ValueError:
                raise exception.InvalidConfigurationValue(
                    option=option,
                    value=iscsi_initiators)
            if not isinstance(self.config.iscsi_initiators, dict):
                raise exception.InvalidConfigurationValue(
                    option=option,
                    value=iscsi_initiators)
            LOG.info(_LI("[%(group)s] iscsi_initiators is configured: "
                         "%(value)s"),
                     {'group': self.config.config_group,
                      'value': self.config.iscsi_initiators})

    def update_volume_stats(self):
        """Retrieves stats info."""
        stats = super(ISCSIAdapter, self).update_volume_stats()
        self.allowed_ports = self.validate_ports(
            self.client.get_iscsi_targets(),
            self.config.io_port_list)
        backend_name = self.config.safe_get('volume_backend_name')
        stats['volume_backend_name'] = backend_name or 'VNXISCSIDriver'
        return stats

    def _build_port_str(self, port):
        return '%(sp)s-%(pid)s-%(vpid)s' % {
            'sp': 'A' if port.sp == storops.VNXSPEnum.SP_A else 'B',
            'pid': port.port_id,
            'vpid': port.vport_id}

    def build_host(self, connector):
        return common.Host(connector['host'], [connector['initiator']],
                           ip=connector['ip'])

    def arrange_io_ports(self, reg_port_white_list, iscsi_initiator_ips):
        """Arranges IO ports.

        Arranges the registered IO ports and puts a pingable port in the
        first place as the main portal.
        """

        random.shuffle(reg_port_white_list)
        random.shuffle(iscsi_initiator_ips)

        main_portal_index = None
        for index, port in enumerate(reg_port_white_list):
            for initiator_ip in iscsi_initiator_ips:
                if self.client.ping_node(port, initiator_ip):
                    main_portal_index = index
                    break
            else:
                # For loop fell through without finding a pingable initiator.
                continue
            break

        if main_portal_index is not None:
            reg_port_white_list.insert(
                0, reg_port_white_list.pop(main_portal_index))

        return reg_port_white_list

    def prepare_target_data(self, storage_group, host, volume, hlu):
        """Prepares the target data for Nova.

        :param storage_group: object of `storops` storage group.
        :param host: `common.Host` object with initiator information.
        :param volume: `common.Volume` object with volume information.
        :param hlu: the HLU number assigned to volume.
        """

        target_io_ports = utils.sift_port_white_list(
            self.allowed_ports, storage_group.get_ports(host.initiators[0]))

        if not target_io_ports:
            msg = (_('Failed to find available iSCSI targets for %s.')
                   % storage_group.name)
            raise exception.VolumeBackendAPIException(data=msg)

        if self.iscsi_initiator_map and host.name in self.iscsi_initiator_map:
            iscsi_initiator_ips = list(self.iscsi_initiator_map[host.name])
            target_io_ports = self.arrange_io_ports(target_io_ports,
                                                    iscsi_initiator_ips)

        iscsi_target_data = common.ISCSITargetData(volume.id, False)
        iqns = [port.wwn for port in target_io_ports]
        portals = ["%s:3260" % port.ip_address for port in target_io_ports]
        iscsi_target_data = common.ISCSITargetData(
            volume.id, True, iqn=iqns[0], iqns=iqns, portal=portals[0],
            portals=portals, lun=hlu, luns=[hlu] * len(target_io_ports))
        LOG.debug('Prepared iSCSI targets for %(host)s: %(target_data)s.',
                  {'host': host.name, 'target_data': iscsi_target_data})

        return iscsi_target_data.to_dict()

    def build_terminate_connection_return_data(self, host, sg):
        return None


class FCAdapter(CommonAdapter):
    def __init__(self, configuration, active_backend_id):
        super(FCAdapter, self).__init__(configuration, active_backend_id)
        self.lookup_service = None

    def do_setup(self):
        super(FCAdapter, self).do_setup()

        self.lookup_service = zm_utils.create_lookup_service()
        self.allowed_ports = self.validate_ports(
            self.client.get_fc_targets(),
            self.config.io_port_list)
        LOG.debug('[%(group)s] allowed_ports are: [%(ports)s].',
                  {'group': self.config.config_group,
                   'ports': ','.join(
                       [port.display_name for port in self.allowed_ports])})

    def update_volume_stats(self):
        """Retrieves stats info."""
        stats = super(FCAdapter, self).update_volume_stats()
        backend_name = self.config.safe_get('volume_backend_name')
        stats['volume_backend_name'] = backend_name or 'VNXFCDriver'
        return stats

    def _build_port_str(self, port):
        return '%(sp)s-%(pid)s' % {
            'sp': 'A' if port.sp == storops.VNXSPEnum.SP_A else 'B',
            'pid': port.port_id}

    def build_host(self, connector):
        if 'wwnns' not in connector or 'wwpns' not in connector:
            msg = _('Host %s has no FC initiators') % connector['host']
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        wwnns = connector['wwnns']
        wwpns = connector['wwpns']
        wwns = [(node + port).upper() for (node, port) in zip(wwnns, wwpns)]
        # WWNS is like '20000090FA534CD110000090FA534CD1', convert it to
        # '20:00:00:90:FA:53:4C:D1:10:00:00:90:FA:53:4C:D1'
        # Note that use // division operator due to the change behavior of
        # / division operator in Python 3.
        wwns = [re.sub(r'\S\S', lambda m: m.group(0) + ':', wwn,
                       len(wwn) // 2 - 1)
                for wwn in wwns]

        return common.Host(connector['host'], wwns, wwpns=wwpns)

    def prepare_target_data(self, storage_group, host, volume, hlu):
        """Prepares the target data for Nova.

        :param storage_group: object of `storops` storage group.
        :param host: `common.Host` object with initiator information.
        :param volume: `common.Volume` object with volume information.
        :param hlu: the HLU number assigned to volume.
        """

        if self.lookup_service is None:
            registed_ports = []
            for wwn in host.initiators:
                registed_ports.extend(storage_group.get_ports(wwn))

            reg_port_white_list = utils.sift_port_white_list(
                self.allowed_ports,
                registed_ports)

            if not reg_port_white_list:
                msg = (_('Failed to find available FC targets for %s.')
                       % storage_group.name)
                raise exception.VolumeBackendAPIException(data=msg)

            target_wwns = [utils.truncate_fc_port_wwn(port.wwn)
                           for port in reg_port_white_list]
            return common.FCTargetData(volume.id, True, wwn=target_wwns,
                                       lun=hlu).to_dict()
        else:
            target_wwns, initiator_target_map = (
                self._get_tgt_list_and_initiator_tgt_map(
                    storage_group, host, True))
            return common.FCTargetData(
                volume.id, True, wwn=target_wwns, lun=hlu,
                initiator_target_map=initiator_target_map).to_dict()

    def update_storage_group_if_required(self, sg):
        if sg.existed and (self.destroy_empty_sg or self.lookup_service):
            utils.update_res_with_poll(sg)

    def build_terminate_connection_return_data(self, host, sg):
        conn_info = {'driver_volume_type': 'fibre_channel',
                     'data': {}}
        if self.lookup_service is None:
            return conn_info

        if not sg.existed or self.client.sg_has_lun_attached(sg):
            return conn_info

        itor_tgt_map = self._get_initiator_tgt_map(sg, host, False)
        conn_info['data']['initiator_target_map'] = itor_tgt_map

        return conn_info

    def _get_initiator_tgt_map(
            self, sg, host, allowed_port_only=False):
        return self._get_tgt_list_and_initiator_tgt_map(
            sg, host, allowed_port_only)[1]

    def _get_tgt_list_and_initiator_tgt_map(
            self, sg, host, allowed_port_only=False):
        fc_initiators = host.wwpns
        fc_ports_wwns = list(map(utils.truncate_fc_port_wwn,
                                 self._get_wwns_of_online_fc_ports(
                                     sg, allowed_port_only=allowed_port_only)))
        mapping = (
            self.lookup_service.
            get_device_mapping_from_network(fc_initiators, fc_ports_wwns))
        return utils.convert_to_tgt_list_and_itor_tgt_map(mapping)

    def _get_wwns_of_online_fc_ports(self, sg, allowed_port_only=False):
        ports = sg.fc_ports
        if allowed_port_only:
            ports = list(filter(lambda po: self._is_allowed_port(po), ports))

        fc_port_wwns = self.client.get_wwn_of_online_fc_ports(ports)

        return fc_port_wwns
