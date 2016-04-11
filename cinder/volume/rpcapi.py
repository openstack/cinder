# Copyright 2012, Intel, Inc.
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
Client side of the volume RPC API.
"""

from oslo_config import cfg
from oslo_serialization import jsonutils

from cinder import exception
from cinder.i18n import _
from cinder import quota
from cinder import rpc
from cinder.volume import utils


CONF = cfg.CONF
QUOTAS = quota.QUOTAS


class VolumeAPI(rpc.RPCAPI):
    """Client side of the volume rpc API.

    API version history:

        1.0 - Initial version.
        1.1 - Adds clone volume option to create_volume.
        1.2 - Add publish_service_capabilities() method.
        1.3 - Pass all image metadata (not just ID) in copy_volume_to_image.
        1.4 - Add request_spec, filter_properties and
              allow_reschedule arguments to create_volume().
        1.5 - Add accept_transfer.
        1.6 - Add extend_volume.
        1.7 - Adds host_name parameter to attach_volume()
              to allow attaching to host rather than instance.
        1.8 - Add migrate_volume, rename_volume.
        1.9 - Add new_user and new_project to accept_transfer.
        1.10 - Add migrate_volume_completion, remove rename_volume.
        1.11 - Adds mode parameter to attach_volume()
               to support volume read-only attaching.
        1.12 - Adds retype.
        1.13 - Adds create_export.
        1.14 - Adds reservation parameter to extend_volume().
        1.15 - Adds manage_existing and unmanage_only flag to delete_volume.
        1.16 - Removes create_export.
        1.17 - Add replica option to create_volume, promote_replica and
               sync_replica.
        1.18 - Adds create_consistencygroup, delete_consistencygroup,
               create_cgsnapshot, and delete_cgsnapshot. Also adds
               the consistencygroup_id parameter in create_volume.
        1.19 - Adds update_migrated_volume
        1.20 - Adds support for sending objects over RPC in create_snapshot()
               and delete_snapshot()
        1.21 - Adds update_consistencygroup.
        1.22 - Adds create_consistencygroup_from_src.
        1.23 - Adds attachment_id to detach_volume.
        1.24 - Removed duplicated parameters: snapshot_id, image_id,
               source_volid, source_replicaid, consistencygroup_id and
               cgsnapshot_id from create_volume. All off them are already
               passed either in request_spec or available in the DB.
        1.25 - Add source_cg to create_consistencygroup_from_src.
        1.26 - Adds support for sending objects over RPC in
               create_consistencygroup(), create_consistencygroup_from_src(),
               update_consistencygroup() and delete_consistencygroup().
        1.27 - Adds support for replication V2
        1.28 - Adds manage_existing_snapshot
        1.29 - Adds get_capabilities.
        1.30 - Adds remove_export
        1.31 - Updated: create_consistencygroup_from_src(), create_cgsnapshot()
               and delete_cgsnapshot() to cast method only with necessary
               args. Forwarding CGSnapshot object instead of CGSnapshot_id.
        1.32 - Adds support for sending objects over RPC in create_volume().
        1.33 - Adds support for sending objects over RPC in delete_volume().
        1.34 - Adds support for sending objects over RPC in retype().
        1.35 - Adds support for sending objects over RPC in extend_volume().
        1.36 - Adds support for sending objects over RPC in migrate_volume(),
               migrate_volume_completion(), and update_migrated_volume().
        1.37 - Adds old_reservations parameter to retype to support quota
               checks in the API.
        1.38 - Scaling backup service, add get_backup_device() and
               secure_file_operations_enabled()
        1.39 - Update replication methods to reflect new backend rep strategy
        1.40 - Add cascade option to delete_volume().

        ... Mitaka supports messaging version 1.40. Any changes to existing
        methods in 1.x after that point should be done so that they can handle
        the version_cap being set to 1.40.

        2.0  - Remove 1.x compatibility
    """

    RPC_API_VERSION = '1.40'
    TOPIC = CONF.volume_topic
    BINARY = 'cinder-volume'

    def _compat_ver(self, current, legacy):
        if self.client.can_send_version(current):
            return current
        else:
            return legacy

    def _get_cctxt(self, host, version):
        new_host = utils.get_volume_rpc_host(host)
        return self.client.prepare(server=new_host, version=version)

    def create_consistencygroup(self, ctxt, group, host):
        version = self._compat_ver('2.0', '1.26')
        cctxt = self._get_cctxt(host, version)
        cctxt.cast(ctxt, 'create_consistencygroup',
                   group=group)

    def delete_consistencygroup(self, ctxt, group):
        version = self._compat_ver('2.0', '1.26')
        cctxt = self._get_cctxt(group.host, version)
        cctxt.cast(ctxt, 'delete_consistencygroup',
                   group=group)

    def update_consistencygroup(self, ctxt, group, add_volumes=None,
                                remove_volumes=None):
        version = self._compat_ver('2.0', '1.26')
        cctxt = self._get_cctxt(group.host, version)
        cctxt.cast(ctxt, 'update_consistencygroup',
                   group=group,
                   add_volumes=add_volumes,
                   remove_volumes=remove_volumes)

    def create_consistencygroup_from_src(self, ctxt, group, cgsnapshot=None,
                                         source_cg=None):
        version = self._compat_ver('2.0', '1.31')
        cctxt = self._get_cctxt(group.host, version)
        cctxt.cast(ctxt, 'create_consistencygroup_from_src',
                   group=group,
                   cgsnapshot=cgsnapshot,
                   source_cg=source_cg)

    def create_cgsnapshot(self, ctxt, cgsnapshot):
        version = self._compat_ver('2.0', '1.31')
        cctxt = self._get_cctxt(cgsnapshot.consistencygroup.host, version)
        cctxt.cast(ctxt, 'create_cgsnapshot', cgsnapshot=cgsnapshot)

    def delete_cgsnapshot(self, ctxt, cgsnapshot):
        version = self._compat_ver('2.0', '1.31')
        cctxt = self._get_cctxt(cgsnapshot.consistencygroup.host, version)
        cctxt.cast(ctxt, 'delete_cgsnapshot', cgsnapshot=cgsnapshot)

    def create_volume(self, ctxt, volume, host, request_spec,
                      filter_properties, allow_reschedule=True):
        request_spec_p = jsonutils.to_primitive(request_spec)
        msg_args = {'volume_id': volume.id, 'request_spec': request_spec_p,
                    'filter_properties': filter_properties,
                    'allow_reschedule': allow_reschedule}
        if self.client.can_send_version('2.0'):
            version = '2.0'
            msg_args['volume'] = volume
        elif self.client.can_send_version('1.32'):
            version = '1.32'
            msg_args['volume'] = volume
        else:
            version = '1.24'

        cctxt = self._get_cctxt(host, version)
        request_spec_p = jsonutils.to_primitive(request_spec)
        cctxt.cast(ctxt, 'create_volume', **msg_args)

    def delete_volume(self, ctxt, volume, unmanage_only=False, cascade=False):
        msg_args = {'volume_id': volume.id, 'unmanage_only': unmanage_only}

        version = '1.15'

        if self.client.can_send_version('2.0'):
            version = '2.0'
            msg_args['volume'] = volume
            if cascade:
                msg_args['cascade'] = cascade
        elif self.client.can_send_version('1.40'):
            version = '1.40'
            msg_args['volume'] = volume
            if cascade:
                msg_args['cascade'] = cascade
        elif cascade:
            msg = _('Cascade option is not supported.')
            raise exception.Invalid(reason=msg)
        elif self.client.can_send_version('1.33'):
            version = '1.33'
            msg_args['volume'] = volume

        cctxt = self._get_cctxt(volume.host, version)
        cctxt.cast(ctxt, 'delete_volume', **msg_args)

    def create_snapshot(self, ctxt, volume, snapshot):
        version = self._compat_ver('2.0', '1.20')
        cctxt = self._get_cctxt(volume['host'], version=version)
        cctxt.cast(ctxt, 'create_snapshot', volume_id=volume['id'],
                   snapshot=snapshot)

    def delete_snapshot(self, ctxt, snapshot, host, unmanage_only=False):
        version = self._compat_ver('2.0', '1.20')
        cctxt = self._get_cctxt(host, version=version)
        cctxt.cast(ctxt, 'delete_snapshot', snapshot=snapshot,
                   unmanage_only=unmanage_only)

    def attach_volume(self, ctxt, volume, instance_uuid, host_name,
                      mountpoint, mode):
        version = self._compat_ver('2.0', '1.11')
        cctxt = self._get_cctxt(volume['host'], version)
        return cctxt.call(ctxt, 'attach_volume',
                          volume_id=volume['id'],
                          instance_uuid=instance_uuid,
                          host_name=host_name,
                          mountpoint=mountpoint,
                          mode=mode)

    def detach_volume(self, ctxt, volume, attachment_id):
        version = self._compat_ver('2.0', '1.20')
        cctxt = self._get_cctxt(volume['host'], version)
        return cctxt.call(ctxt, 'detach_volume', volume_id=volume['id'],
                          attachment_id=attachment_id)

    def copy_volume_to_image(self, ctxt, volume, image_meta):
        version = self._compat_ver('2.0', '1.3')
        cctxt = self._get_cctxt(volume['host'], version)
        cctxt.cast(ctxt, 'copy_volume_to_image', volume_id=volume['id'],
                   image_meta=image_meta)

    def initialize_connection(self, ctxt, volume, connector):
        version = self._compat_ver('2.0', '1.0')
        cctxt = self._get_cctxt(volume['host'], version=version)
        return cctxt.call(ctxt, 'initialize_connection',
                          volume_id=volume['id'],
                          connector=connector)

    def terminate_connection(self, ctxt, volume, connector, force=False):
        version = self._compat_ver('2.0', '1.0')
        cctxt = self._get_cctxt(volume['host'], version=version)
        return cctxt.call(ctxt, 'terminate_connection', volume_id=volume['id'],
                          connector=connector, force=force)

    def remove_export(self, ctxt, volume):
        version = self._compat_ver('2.0', '1.30')
        cctxt = self._get_cctxt(volume['host'], version)
        cctxt.cast(ctxt, 'remove_export', volume_id=volume['id'])

    def publish_service_capabilities(self, ctxt):
        version = self._compat_ver('2.0', '1.2')
        cctxt = self.client.prepare(fanout=True, version=version)
        cctxt.cast(ctxt, 'publish_service_capabilities')

    def accept_transfer(self, ctxt, volume, new_user, new_project):
        version = self._compat_ver('2.0', '1.9')
        cctxt = self._get_cctxt(volume['host'], version)
        return cctxt.call(ctxt, 'accept_transfer', volume_id=volume['id'],
                          new_user=new_user, new_project=new_project)

    def extend_volume(self, ctxt, volume, new_size, reservations):
        msg_args = {'volume_id': volume.id, 'new_size': new_size,
                    'reservations': reservations}
        if self.client.can_send_version('2.0'):
            version = '2.0'
            msg_args['volume'] = volume
        elif self.client.can_send_version('1.35'):
            version = '1.35'
            msg_args['volume'] = volume
        else:
            version = '1.14'

        cctxt = self._get_cctxt(volume.host, version)
        cctxt.cast(ctxt, 'extend_volume', **msg_args)

    def migrate_volume(self, ctxt, volume, dest_host, force_host_copy):
        host_p = {'host': dest_host.host,
                  'capabilities': dest_host.capabilities}

        msg_args = {'volume_id': volume.id, 'host': host_p,
                    'force_host_copy': force_host_copy}
        if self.client.can_send_version('2.0'):
            version = '2.0'
            msg_args['volume'] = volume
        elif self.client.can_send_version('1.36'):
            version = '1.36'
            msg_args['volume'] = volume
        else:
            version = '1.8'

        cctxt = self._get_cctxt(volume.host, version)
        cctxt.cast(ctxt, 'migrate_volume', **msg_args)

    def migrate_volume_completion(self, ctxt, volume, new_volume, error):

        msg_args = {'volume_id': volume.id, 'new_volume_id': new_volume.id,
                    'error': error}
        if self.client.can_send_version('2.0'):
            version = '2.0'
            msg_args['volume'] = volume
            msg_args['new_volume'] = new_volume
        elif self.client.can_send_version('1.36'):
            version = '1.36'
            msg_args['volume'] = volume
            msg_args['new_volume'] = new_volume
        else:
            version = '1.10'

        cctxt = self._get_cctxt(volume.host, version)
        return cctxt.call(ctxt, 'migrate_volume_completion', **msg_args)

    def retype(self, ctxt, volume, new_type_id, dest_host,
               migration_policy='never', reservations=None,
               old_reservations=None):
        host_p = {'host': dest_host.host,
                  'capabilities': dest_host.capabilities}
        msg_args = {'volume_id': volume.id, 'new_type_id': new_type_id,
                    'host': host_p, 'migration_policy': migration_policy,
                    'reservations': reservations}
        if self.client.can_send_version('2.0'):
            version = '2.0'
            msg_args.update(volume=volume, old_reservations=old_reservations)
        elif self.client.can_send_version('1.37'):
            version = '1.37'
            msg_args.update(volume=volume, old_reservations=old_reservations)
        elif self.client.can_send_version('1.34'):
            if old_reservations is not None:
                QUOTAS.rollback(ctxt, old_reservations)
            version = '1.34'
            msg_args['volume'] = volume
        else:
            if old_reservations is not None:
                QUOTAS.rollback(ctxt, old_reservations)
            version = '1.12'

        cctxt = self._get_cctxt(volume.host, version)
        cctxt.cast(ctxt, 'retype', **msg_args)

    def manage_existing(self, ctxt, volume, ref):
        version = self._compat_ver('2.0', '1.15')
        cctxt = self._get_cctxt(volume['host'], version)
        cctxt.cast(ctxt, 'manage_existing', volume_id=volume['id'], ref=ref)

    def promote_replica(self, ctxt, volume):
        version = self._compat_ver('2.0', '1.17')
        cctxt = self._get_cctxt(volume['host'], version)
        cctxt.cast(ctxt, 'promote_replica', volume_id=volume['id'])

    def reenable_replication(self, ctxt, volume):
        version = self._compat_ver('2.0', '1.17')
        cctxt = self._get_cctxt(volume['host'], version)
        cctxt.cast(ctxt, 'reenable_replication', volume_id=volume['id'])

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        version = self._compat_ver('2.0', '1.36')
        cctxt = self._get_cctxt(new_volume['host'], version)
        cctxt.call(ctxt,
                   'update_migrated_volume',
                   volume=volume,
                   new_volume=new_volume,
                   volume_status=original_volume_status)

    def freeze_host(self, ctxt, host):
        """Set backend host to frozen."""
        version = self._compat_ver('2.0', '1.39')
        cctxt = self._get_cctxt(host, version)
        return cctxt.call(ctxt, 'freeze_host')

    def thaw_host(self, ctxt, host):
        """Clear the frozen setting on a backend host."""
        version = self._compat_ver('2.0', '1.39')
        cctxt = self._get_cctxt(host, version)
        return cctxt.call(ctxt, 'thaw_host')

    def failover_host(self, ctxt, host,
                      secondary_backend_id=None):
        """Failover host to the specified backend_id (secondary). """
        version = self._compat_ver('2.0', '1.39')
        cctxt = self._get_cctxt(host, version)
        cctxt.cast(ctxt, 'failover_host',
                   secondary_backend_id=secondary_backend_id)

    def manage_existing_snapshot(self, ctxt, snapshot, ref, host):
        version = self._compat_ver('2.0', '1.28')
        cctxt = self._get_cctxt(host, version)
        cctxt.cast(ctxt, 'manage_existing_snapshot',
                   snapshot=snapshot,
                   ref=ref)

    def get_capabilities(self, ctxt, host, discover):
        version = self._compat_ver('2.0', '1.29')
        cctxt = self._get_cctxt(host, version)
        return cctxt.call(ctxt, 'get_capabilities', discover=discover)

    def get_backup_device(self, ctxt, backup, volume):
        if (not self.client.can_send_version('1.38') and
                not self.client.can_send_version('2.0')):
            msg = _('One of cinder-volume services is too old to accept such '
                    'request. Are you running mixed Liberty-Mitaka '
                    'cinder-volumes?')
            raise exception.ServiceTooOld(msg)
        version = self._compat_ver('2.0', '1.38')
        cctxt = self._get_cctxt(volume.host, version)
        return cctxt.call(ctxt, 'get_backup_device',
                          backup=backup)

    def secure_file_operations_enabled(self, ctxt, volume):
        if (not self.client.can_send_version('1.38') and
                not self.client.can_send_version('2.0')):
            msg = _('One of cinder-volume services is too old to accept such '
                    'request. Are you running mixed Liberty-Mitaka '
                    'cinder-volumes?')
            raise exception.ServiceTooOld(msg)
        version = self._compat_ver('2.0', '1.38')
        cctxt = self._get_cctxt(volume.host, version)
        return cctxt.call(ctxt, 'secure_file_operations_enabled',
                          volume=volume)
