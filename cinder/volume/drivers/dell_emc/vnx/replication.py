# Copyright (c) 2017 Dell Inc. or its subsidiaries.
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

from oslo_log import log as logging
from oslo_utils import importutils

from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder.volume.drivers.dell_emc.vnx import client
from cinder.volume.drivers.dell_emc.vnx import common
from cinder.volume.drivers.dell_emc.vnx import taskflows as emc_taskflow
from cinder.volume.drivers.dell_emc.vnx import utils

storops = importutils.try_import('storops')
if storops:
    from storops import exception as storops_ex


LOG = logging.getLogger(__name__)


class ReplicationAdapter(object):

    def __init__(self, client=None, config=None):
        self.client = client
        self.config = config
        self.mirror_view = None

    def do_setup(self):
        pass

    def setup_lun_replication(self, volume, primary_lun_id):
        """Setup replication for LUN, this only happens in primary system."""
        specs = common.ExtraSpecs.from_volume(volume)
        provision = specs.provision
        tier = specs.tier
        rep_update = {'replication_driver_data': None,
                      'replication_status': fields.ReplicationStatus.DISABLED}
        mirror_name = utils.construct_mirror_name(volume)

        if specs.is_replication_enabled:
            LOG.debug('Starting setup replication '
                      'for volume: %s.', volume.id)
            lun_size = volume.size
            pool_name = utils.get_remote_pool(self.config, volume)
            emc_taskflow.create_mirror_view(
                self.mirror_view, mirror_name,
                primary_lun_id, pool_name,
                volume.name, lun_size,
                provision, tier)
            LOG.info('Successfully setup replication for %s.', volume.id)
            rep_update.update({'replication_status':
                               fields.ReplicationStatus.ENABLED})
        group_specs = common.ExtraSpecs.from_group(volume.group)
        if volume.group and group_specs.is_group_replication_enabled:
            # If in a group, add it to group then.
            LOG.debug('Starting add volume %(volume)s to group %(group)s',
                      {'volume': volume.id, 'group': volume.group.id})
            group_name = utils.construct_group_name(volume.group)
            self.client.add_mirror(group_name, mirror_name)

        return rep_update

    def create_group_replication(self, group):
        rep_update = {'replication_status': group.replication_status}

        group_specs = common.ExtraSpecs.from_group(group)
        if group_specs.is_group_replication_enabled:
            group_name = utils.construct_group_name(group)
            self.client.create_mirror_group(group_name)
            rep_update['replication_status'] = (
                fields.ReplicationStatus.ENABLED)
        return rep_update

    def add_volumes_to_group_replication(self, group, volumes):
        group_specs = common.ExtraSpecs.from_group(group)
        if group_specs.is_group_replication_enabled:
            group_name = utils.construct_group_name(group)
            for volume in volumes:
                mirror_name = utils.construct_mirror_name(volume)
                self.client.add_mirror(group_name, mirror_name)

    def delete_group_replication(self, group):
        group_specs = common.ExtraSpecs.from_group(group)
        if group_specs.is_group_replication_enabled:
            group_name = utils.construct_group_name(group)
            self.client.delete_mirror_group(group_name)

    def remove_volumes_from_group_replication(self, group, volumes):
        group_name = utils.construct_group_name(group)
        group_specs = common.ExtraSpecs.from_group(group)
        if group_specs.is_group_replication_enabled:
            for volume in volumes:
                mirror_name = utils.construct_mirror_name(volume)
                self.client.remove_mirror(group_name, mirror_name)

    def cleanup_lun_replication(self, volume):
        specs = common.ExtraSpecs.from_volume(volume)

        group_specs = common.ExtraSpecs.from_group(volume.group)
        if group_specs.is_group_replication_enabled:
            # If in a group, remove from group first.
            group_name = utils.construct_group_name(volume.group)
            mirror_name = utils.construct_mirror_name(volume)
            self.client.remove_mirror(group_name, mirror_name)

        if specs.is_replication_enabled:
            LOG.debug('Starting cleanup replication for volume: '
                      '%s.', volume.id)
            mirror_name = utils.construct_mirror_name(volume)
            mirror_view = self.build_mirror_view(self.config, True)
            mirror_view.destroy_mirror(mirror_name, volume.name)
            LOG.info(
                'Successfully destroyed replication for volume: %s',
                volume.id)

    def append_replication_stats(self, stats):
        if self.mirror_view:
            stats['replication_enabled'] = True
            stats['group_replication_enabled'] = False
            stats['consistent_group_replication_enabled'] = True
            stats['replication_count'] = 1
            stats['replication_type'] = ['sync']
        else:
            stats['replication_enabled'] = False
        stats['replication_targets'] = [
            device.backend_id for device in common.ReplicationDeviceList(
                self.config)]

    def build_mirror_view(self, configuration, failover=True):
        """Builds a mirror view operation class.

        :param configuration: driver configuration
        :param failover: True if from primary to configured array,
                         False if from configured array to primary.
        """
        rep_devices = configuration.replication_device
        if not rep_devices:
            LOG.info('Replication is not configured on backend: %s.',
                     configuration.config_group)
            return None
        elif len(rep_devices) == 1:
            if not self.client.is_mirror_view_enabled():
                error_msg = _('Replication is configured, '
                              'but no MirrorView/S enabler installed on VNX.')
                raise exception.InvalidInput(reason=error_msg)
            rep_list = common.ReplicationDeviceList(configuration)
            device = rep_list[0]
            # primary_client always points to the configed VNX.
            primary_client = self._build_client_from_config(self.config)
            # secondary_client always points to the VNX in replication_device.
            secondary_client = client.Client(
                ip=device.san_ip,
                username=device.san_login,
                password=device.san_password,
                scope=device.storage_vnx_authentication_type,
                naviseccli=self.client.naviseccli,
                sec_file=device.storage_vnx_security_file_dir)
            if failover:
                mirror_view = common.VNXMirrorView(
                    primary_client, secondary_client)
            else:
                # For fail-back, we need to take care of reversed ownership.
                mirror_view = common.VNXMirrorView(
                    secondary_client, primary_client)
            return mirror_view
        else:
            error_msg = _('VNX Cinder driver does not support '
                          'multiple replication targets.')
            raise exception.InvalidInput(reason=error_msg)

    def validate_backend_id(self, backend_id):
        # Currently, VNX driver only supports 1 remote device.
        if self.active_backend_id:
            if backend_id != 'default':
                raise exception.InvalidReplicationTarget(
                    reason=_('Invalid backend_id specified.'))
        elif backend_id not in (
                common.ReplicationDeviceList.get_backend_ids(self.config)):
            raise exception.InvalidReplicationTarget(
                reason=_('Invalid backend_id specified.'))

    def failover_host(self, context, volumes, secondary_backend_id, groups):
        """Fails over the volume back and forth.

        Driver needs to update following info for failed-over volume:
        1. provider_location: update serial number and lun id
        2. replication_status: new status for replication-enabled volume
        """
        volume_update_list = []
        group_update_list = []
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
                LOG.error(
                    'Failed to failover volume %(volume_id)s '
                    'to %(target)s: %(error)s.',
                    {'volume_id': volume.id,
                     'target': secondary_backend_id,
                     'error': ex})
                new_status = fields.ReplicationStatus.FAILOVER_ERROR
            else:
                # Transfer ownership to secondary_backend_id and
                # update provider_location field
                secondary_client = mirror_view.secondary_client
                provider_location = utils.update_remote_provider_location(
                    volume, secondary_client)

            model_update = {'volume_id': volume.id,
                            'updates':
                                {'replication_status': new_status,
                                 'provider_location': provider_location}}
            volume_update_list.append(model_update)

        # Fail over groups if needed.
        def failover_group(group):
            is_failover_needed = False
            if (secondary_backend_id != 'default' and
                    group.replication_status ==
                    fields.ReplicationStatus.ENABLED):
                # Group is on the primary VNX, failover is needed.
                LOG.info('%(group_id)s will be failed over to secondary'
                         '%(secondary_backend_id)s.',
                         {'group_id': group.id,
                          'secondary_backend_id': secondary_backend_id})
                is_failover_needed = True
            if (secondary_backend_id == 'default' and
                    group.replication_status ==
                    fields.ReplicationStatus.FAILED_OVER):
                # Group is on the secondary VNX, failover is needed.
                LOG.info('%(group_id)s will be failed over to primary'
                         '%(secondary_backend_id)s.',
                         {'group_id': group.id,
                          'secondary_backend_id': secondary_backend_id})
                is_failover_needed = True
            if is_failover_needed:
                group_update, volume_update_list = self.failover_replication(
                    context, group, group.volumes, secondary_backend_id)
                return ({'group_id': group.id, 'updates': group_update},
                        [{'volume_id': vol_update['id'], 'updates': vol_update}
                        for vol_update in volume_update_list])

            return [], []

        for group in groups:
            specs = common.ExtraSpecs.from_group(group)
            if specs.is_group_replication_enabled:
                group_update, vols_in_group_update = failover_group(group)
                if group_update:
                    group_update_list.append(group_update)
                    volume_update_list.extend(vols_in_group_update)

        # Filter out the volumes in passed-in groups.
        group_ids = [group.id for group in groups]
        for volume in [volume for volume in volumes
                       if volume.group_id not in group_ids]:
            specs = common.ExtraSpecs.from_volume(volume)
            if specs.is_replication_enabled:
                failover_volume(volume, rep_status)

        # After failover, the secondary is now the primary,
        # any subsequent request will be redirected to it.
        self.client = mirror_view.secondary_client
        # Remember the current backend id.
        self.active_backend_id = (None if secondary_backend_id == 'default'
                                  else secondary_backend_id)
        return secondary_backend_id, volume_update_list, group_update_list

    def enable_replication(self, context, group, volumes):
        """Enable the group replication.

        Note: this will not interfere with the replication on individual LUNs.
        """
        self.create_group_replication(group)
        self.add_volumes_to_group_replication(group, volumes)
        return {}, []

    def disable_replication(self, context, group, volumes):
        """Disable the group replication.

        Note: This will not disable the replication on individual LUNs.
        """
        self.remove_volumes_from_group_replication(group, volumes)
        self.delete_group_replication(group)
        return {}, []

    def failover_replication(self, context, group, volumes,
                             secondary_backend_id):
        """"Fail-over the consistent mirror group.

        Note:
            VNX supports fail over all the mirrors in a group as a whole,
            no need to handle each mirror one by one.
        """
        volume_update_list = []
        group_update = {'replication_status': group.replication_status}

        if secondary_backend_id != 'default':
            mirror_view = self.build_mirror_view(self.config, True)
            rep_status = fields.ReplicationStatus.FAILED_OVER
        else:
            mirror_view = self.build_mirror_view(self.config, False)
            rep_status = fields.ReplicationStatus.ENABLED

        # Update volume provider_location
        secondary_client = mirror_view.secondary_client

        group_name = utils.construct_group_name(group)
        try:
            mirror_view.promote_mirror_group(group_name)
        except storops_ex.VNXMirrorException as ex:
            LOG.error(
                'Failed to failover group %(group_id)s '
                'to %(target)s: %(error)s.',
                {'group_id': group.id,
                 'target': secondary_backend_id,
                 'error': ex})
            rep_status = fields.ReplicationStatus.FAILOVER_ERROR

        for volume in volumes:
            volume_update = {
                'id': volume.id,
                'provider_location': utils.update_remote_provider_location(
                    volume, secondary_client),
                'replication_status': rep_status}
            volume_update_list.append(volume_update)

        group_update['replication_status'] = rep_status

        return group_update, volume_update_list

    def get_replication_error_status(self, context, groups):
        """The failover only happens manually, no need to update the status."""
        return [], []
