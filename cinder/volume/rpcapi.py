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


from oslo_serialization import jsonutils

from cinder.common import constants
from cinder import objects
from cinder import quota
from cinder import rpc
from cinder.volume import utils


QUOTAS = quota.QUOTAS


class VolumeAPI(rpc.RPCAPI):
    """Client side of the volume rpc API.

    API version history:

    .. code-block:: none

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
        2.1  - Add get_manageable_volumes() and get_manageable_snapshots().
        2.2  - Adds support for sending objects over RPC in manage_existing().
        2.3  - Adds support for sending objects over RPC in
               initialize_connection().
        2.4  - Sends request_spec as object in create_volume().
        2.5  - Adds create_group, delete_group, and update_group
        2.6  - Adds create_group_snapshot, delete_group_snapshot, and
               create_group_from_src().

        ... Newton supports messaging version 2.6. Any changes to existing
        methods in 2.x after that point should be done so that they can handle
        the version_cap being set to 2.6.

        3.0  - Drop 2.x compatibility
    """

    RPC_API_VERSION = '3.0'
    TOPIC = constants.VOLUME_TOPIC
    BINARY = 'cinder-volume'

    def _get_cctxt(self, host, version):
        new_host = utils.get_volume_rpc_host(host)
        return self.client.prepare(server=new_host, version=version)

    def create_consistencygroup(self, ctxt, group, host):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(host, version)
        cctxt.cast(ctxt, 'create_consistencygroup',
                   group=group)

    def delete_consistencygroup(self, ctxt, group):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(group.host, version)
        cctxt.cast(ctxt, 'delete_consistencygroup',
                   group=group)

    def update_consistencygroup(self, ctxt, group, add_volumes=None,
                                remove_volumes=None):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(group.host, version)
        cctxt.cast(ctxt, 'update_consistencygroup',
                   group=group,
                   add_volumes=add_volumes,
                   remove_volumes=remove_volumes)

    def create_consistencygroup_from_src(self, ctxt, group, cgsnapshot=None,
                                         source_cg=None):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(group.host, version)
        cctxt.cast(ctxt, 'create_consistencygroup_from_src',
                   group=group,
                   cgsnapshot=cgsnapshot,
                   source_cg=source_cg)

    def create_cgsnapshot(self, ctxt, cgsnapshot):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(cgsnapshot.consistencygroup.host, version)
        cctxt.cast(ctxt, 'create_cgsnapshot', cgsnapshot=cgsnapshot)

    def delete_cgsnapshot(self, ctxt, cgsnapshot):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(cgsnapshot.consistencygroup.host, version)
        cctxt.cast(ctxt, 'delete_cgsnapshot', cgsnapshot=cgsnapshot)

    def create_volume(self, ctxt, volume, host, request_spec,
                      filter_properties, allow_reschedule=True):
        msg_args = {'request_spec': request_spec,
                    'filter_properties': filter_properties,
                    'allow_reschedule': allow_reschedule,
                    'volume': volume,
                    }
        version = self._compat_ver('3.0', '2.4', '2.0')
        if version in ('2.4', '2.0'):
            msg_args['volume_id'] = volume.id
        if version == '2.0':
            # Send request_spec as dict
            msg_args['request_spec'] = jsonutils.to_primitive(request_spec)

        cctxt = self._get_cctxt(host, version)
        cctxt.cast(ctxt, 'create_volume', **msg_args)

    def delete_volume(self, ctxt, volume, unmanage_only=False, cascade=False):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume.host, version)
        msg_args = {
            'volume': volume, 'unmanage_only': unmanage_only,
            'cascade': cascade,
        }

        if version == '2.0':
            msg_args['volume_id'] = volume.id

        cctxt.cast(ctxt, 'delete_volume', **msg_args)

    def create_snapshot(self, ctxt, volume, snapshot):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume['host'], version)
        msg_args = {
            'snapshot': snapshot,
        }

        if version == '2.0':
            msg_args['volume_id'] = volume['id']

        cctxt.cast(ctxt, 'create_snapshot', **msg_args)

    def delete_snapshot(self, ctxt, snapshot, host, unmanage_only=False):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(host, version)
        cctxt.cast(ctxt, 'delete_snapshot', snapshot=snapshot,
                   unmanage_only=unmanage_only)

    def attach_volume(self, ctxt, volume, instance_uuid, host_name,
                      mountpoint, mode):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume['host'], version)
        return cctxt.call(ctxt, 'attach_volume',
                          volume_id=volume['id'],
                          instance_uuid=instance_uuid,
                          host_name=host_name,
                          mountpoint=mountpoint,
                          mode=mode)

    def detach_volume(self, ctxt, volume, attachment_id):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume['host'], version)
        return cctxt.call(ctxt, 'detach_volume', volume_id=volume['id'],
                          attachment_id=attachment_id)

    def copy_volume_to_image(self, ctxt, volume, image_meta):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume['host'], version)
        cctxt.cast(ctxt, 'copy_volume_to_image', volume_id=volume['id'],
                   image_meta=image_meta)

    def initialize_connection(self, ctxt, volume, connector):
        version = self._compat_ver('3.0', '2.3', '2.0')
        msg_args = {'connector': connector, 'volume': volume}

        if version in ('2.0', '2.3'):
            msg_args['volume_id'] = volume.id
        if version == '2.0':
            del msg_args['volume']

        cctxt = self._get_cctxt(volume['host'], version=version)
        return cctxt.call(ctxt, 'initialize_connection', **msg_args)

    def terminate_connection(self, ctxt, volume, connector, force=False):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume['host'], version)
        return cctxt.call(ctxt, 'terminate_connection', volume_id=volume['id'],
                          connector=connector, force=force)

    def remove_export(self, ctxt, volume):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume['host'], version)
        cctxt.cast(ctxt, 'remove_export', volume_id=volume['id'])

    def publish_service_capabilities(self, ctxt):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self.client.prepare(fanout=True, version=version)
        cctxt.cast(ctxt, 'publish_service_capabilities')

    def accept_transfer(self, ctxt, volume, new_user, new_project):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume['host'], version)
        return cctxt.call(ctxt, 'accept_transfer', volume_id=volume['id'],
                          new_user=new_user, new_project=new_project)

    def extend_volume(self, ctxt, volume, new_size, reservations):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume.host, version)
        msg_args = {
            'volume': volume, 'new_size': new_size,
            'reservations': reservations,
        }

        if version == '2.0':
            msg_args['volume_id'] = volume.id

        cctxt.cast(ctxt, 'extend_volume', **msg_args)

    def migrate_volume(self, ctxt, volume, dest_host, force_host_copy):
        host_p = {'host': dest_host.host,
                  'capabilities': dest_host.capabilities}
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume.host, version)

        msg_args = {
            'volume': volume, 'host': host_p,
            'force_host_copy': force_host_copy,
        }

        if version == '2.0':
            msg_args['volume_id'] = volume.id

        cctxt.cast(ctxt, 'migrate_volume', **msg_args)

    def migrate_volume_completion(self, ctxt, volume, new_volume, error):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume.host, version)

        msg_args = {
            'volume': volume, 'new_volume': new_volume, 'error': error,
        }

        if version == '2.0':
            msg_args['volume_id'] = volume.id
            msg_args['new_volume_id'] = new_volume.id

        return cctxt.call(ctxt, 'migrate_volume_completion', **msg_args)

    def retype(self, ctxt, volume, new_type_id, dest_host,
               migration_policy='never', reservations=None,
               old_reservations=None):
        host_p = {'host': dest_host.host,
                  'capabilities': dest_host.capabilities}
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume.host, version)

        msg_args = {
            'volume': volume, 'new_type_id': new_type_id, 'host': host_p,
            'migration_policy': migration_policy, 'reservations': reservations,
            'old_reservations': old_reservations,
        }

        if version == '2.0':
            msg_args['volume_id'] = volume.id

        cctxt.cast(ctxt, 'retype', **msg_args)

    def manage_existing(self, ctxt, volume, ref):
        msg_args = {
            'ref': ref, 'volume': volume,
        }
        version = self._compat_ver('3.0', '2.2', '2.0')
        if version in ('2.2', '2.0'):
            msg_args['volume_id'] = volume.id
        if version == '2.0':
            msg_args.pop('volume')
        cctxt = self._get_cctxt(volume.host, version)
        cctxt.cast(ctxt, 'manage_existing', **msg_args)

    def promote_replica(self, ctxt, volume):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume['host'], version)
        cctxt.cast(ctxt, 'promote_replica', volume_id=volume['id'])

    def reenable_replication(self, ctxt, volume):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume['host'], version)
        cctxt.cast(ctxt, 'reenable_replication', volume_id=volume['id'])

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(new_volume['host'], version)
        cctxt.call(ctxt,
                   'update_migrated_volume',
                   volume=volume,
                   new_volume=new_volume,
                   volume_status=original_volume_status)

    def freeze_host(self, ctxt, host):
        """Set backend host to frozen."""
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(host, version)
        return cctxt.call(ctxt, 'freeze_host')

    def thaw_host(self, ctxt, host):
        """Clear the frozen setting on a backend host."""
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(host, version)
        return cctxt.call(ctxt, 'thaw_host')

    def failover_host(self, ctxt, host, secondary_backend_id=None):
        """Failover host to the specified backend_id (secondary). """
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(host, version)
        cctxt.cast(ctxt, 'failover_host',
                   secondary_backend_id=secondary_backend_id)

    def manage_existing_snapshot(self, ctxt, snapshot, ref, host):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(host, version)
        cctxt.cast(ctxt, 'manage_existing_snapshot',
                   snapshot=snapshot,
                   ref=ref)

    def get_capabilities(self, ctxt, host, discover):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(host, version)
        return cctxt.call(ctxt, 'get_capabilities', discover=discover)

    def get_backup_device(self, ctxt, backup, volume):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume.host, version)
        backup_dict = cctxt.call(ctxt, 'get_backup_device', backup=backup)

        # FIXME(dulek): Snippet below converts received raw dicts to o.vo. This
        # is only for a case when Mitaka's c-vol will answer us with volume
        # dict instead of an o.vo and should go away in early Ocata.
        if isinstance(backup_dict.get('backup_device'), dict):
            is_snapshot = backup_dict.get('is_snapshot')
            obj_class = objects.Snapshot if is_snapshot else objects.Volume
            obj = obj_class()
            obj_class._from_db_object(ctxt, obj, backup_dict['backup_device'])
            backup_dict['backup_device'] = obj

        return backup_dict

    def secure_file_operations_enabled(self, ctxt, volume):
        version = self._compat_ver('3.0', '2.0')
        cctxt = self._get_cctxt(volume.host, version)
        return cctxt.call(ctxt, 'secure_file_operations_enabled',
                          volume=volume)

    def get_manageable_volumes(self, ctxt, host, marker, limit, offset,
                               sort_keys, sort_dirs):
        version = self._compat_ver('3.0', '2.1')
        cctxt = self._get_cctxt(host, version)
        return cctxt.call(ctxt, 'get_manageable_volumes', marker=marker,
                          limit=limit, offset=offset, sort_keys=sort_keys,
                          sort_dirs=sort_dirs)

    def get_manageable_snapshots(self, ctxt, host, marker, limit, offset,
                                 sort_keys, sort_dirs):
        version = self._compat_ver('3.0', '2.1')
        cctxt = self._get_cctxt(host, version)
        return cctxt.call(ctxt, 'get_manageable_snapshots', marker=marker,
                          limit=limit, offset=offset, sort_keys=sort_keys,
                          sort_dirs=sort_dirs)

    def create_group(self, ctxt, group, host):
        version = self._compat_ver('3.0', '2.5')
        cctxt = self._get_cctxt(host, version)
        cctxt.cast(ctxt, 'create_group',
                   group=group)

    def delete_group(self, ctxt, group):
        version = self._compat_ver('3.0', '2.5')
        cctxt = self._get_cctxt(group.host, version)
        cctxt.cast(ctxt, 'delete_group',
                   group=group)

    def update_group(self, ctxt, group, add_volumes=None,
                     remove_volumes=None):
        version = self._compat_ver('3.0', '2.5')
        cctxt = self._get_cctxt(group.host, version)
        cctxt.cast(ctxt, 'update_group',
                   group=group,
                   add_volumes=add_volumes,
                   remove_volumes=remove_volumes)

    def create_group_from_src(self, ctxt, group, group_snapshot=None,
                              source_group=None):
        version = self._compat_ver('3.0', '2.6')
        cctxt = self._get_cctxt(group.host, version)
        cctxt.cast(ctxt, 'create_group_from_src',
                   group=group,
                   group_snapshot=group_snapshot,
                   source_group=source_group)

    def create_group_snapshot(self, ctxt, group_snapshot):
        version = self._compat_ver('3.0', '2.6')
        cctxt = self._get_cctxt(group_snapshot.group.host, version)
        cctxt.cast(ctxt, 'create_group_snapshot',
                   group_snapshot=group_snapshot)

    def delete_group_snapshot(self, ctxt, group_snapshot):
        version = self._compat_ver('3.0', '2.6')
        cctxt = self._get_cctxt(group_snapshot.group.host, version)
        cctxt.cast(ctxt, 'delete_group_snapshot',
                   group_snapshot=group_snapshot)
