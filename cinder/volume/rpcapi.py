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
        3.1  - Remove promote_replica and reenable_replication. This is
               non-backward compatible, but the user-facing API was removed
               back in Mitaka when introducing cheesecake replication.
        3.2  - Adds support for sending objects over RPC in
               get_backup_device().
        3.3  - Adds support for sending objects over RPC in attach_volume().
        3.4  - Adds support for sending objects over RPC in detach_volume().
        3.5  - Adds support for cluster in retype and migrate_volume
        3.6  - Switch to use oslo.messaging topics to indicate backends instead
               of @backend suffixes in server names.
        3.7  - Adds do_cleanup method to do volume cleanups from other nodes
               that we were doing in init_host.
        3.8  - Make failover_host cluster aware and add failover_completed.
        3.9  - Adds new attach/detach methods
        3.10 - Returning objects instead of raw dictionaries in
               get_manageable_volumes & get_manageable_snapshots
        3.11 - Removes create_consistencygroup, delete_consistencygroup,
               create_cgsnapshot, delete_cgsnapshot, update_consistencygroup,
               and create_consistencygroup_from_src.
        3.12 - Adds set_log_levels and get_log_levels
        3.13 - Add initialize_connection_snapshot,
               terminate_connection_snapshot, and remove_export_snapshot.
        3.14 - Adds enable_replication, disable_replication,
               failover_replication, and list_replication_targets.
        3.15 - Add revert_to_snapshot method
        3.16 - Add no_snapshots to accept_transfer method
    """

    RPC_API_VERSION = '3.16'
    RPC_DEFAULT_VERSION = '3.0'
    TOPIC = constants.VOLUME_TOPIC
    BINARY = constants.VOLUME_BINARY

    def _get_cctxt(self, host=None, version=None, **kwargs):
        if host:
            server = utils.extract_host(host)

            # TODO(dulek): If we're pinned before 3.6, we should send stuff the
            # old way - addressing server=host@backend, topic=cinder-volume.
            # Otherwise we're addressing server=host,
            # topic=cinder-volume.host@backend. This conditional can go away
            # when we stop supporting 3.x.
            if self.client.can_send_version('3.6'):
                kwargs['topic'] = '%(topic)s.%(host)s' % {'topic': self.TOPIC,
                                                          'host': server}
                server = utils.extract_host(server, 'host')
            kwargs['server'] = server

        return super(VolumeAPI, self)._get_cctxt(version=version, **kwargs)

    def create_volume(self, ctxt, volume, request_spec, filter_properties,
                      allow_reschedule=True):
        cctxt = self._get_cctxt(volume.service_topic_queue)
        cctxt.cast(ctxt, 'create_volume',
                   request_spec=request_spec,
                   filter_properties=filter_properties,
                   allow_reschedule=allow_reschedule,
                   volume=volume)

    @rpc.assert_min_rpc_version('3.15')
    def revert_to_snapshot(self, ctxt, volume, snapshot):
        version = self._compat_ver('3.15')
        cctxt = self._get_cctxt(volume.service_topic_queue, version)
        cctxt.cast(ctxt, 'revert_to_snapshot', volume=volume,
                   snapshot=snapshot)

    def delete_volume(self, ctxt, volume, unmanage_only=False, cascade=False):
        volume.create_worker()
        cctxt = self._get_cctxt(volume.service_topic_queue)
        msg_args = {
            'volume': volume, 'unmanage_only': unmanage_only,
            'cascade': cascade,
        }

        cctxt.cast(ctxt, 'delete_volume', **msg_args)

    def create_snapshot(self, ctxt, volume, snapshot):
        snapshot.create_worker()
        cctxt = self._get_cctxt(volume.service_topic_queue)
        cctxt.cast(ctxt, 'create_snapshot', snapshot=snapshot)

    def delete_snapshot(self, ctxt, snapshot, unmanage_only=False):
        cctxt = self._get_cctxt(snapshot.service_topic_queue)
        cctxt.cast(ctxt, 'delete_snapshot', snapshot=snapshot,
                   unmanage_only=unmanage_only)

    def attach_volume(self, ctxt, volume, instance_uuid, host_name,
                      mountpoint, mode):
        msg_args = {'volume_id': volume.id,
                    'instance_uuid': instance_uuid,
                    'host_name': host_name,
                    'mountpoint': mountpoint,
                    'mode': mode,
                    'volume': volume}
        cctxt = self._get_cctxt(volume.service_topic_queue, ('3.3', '3.0'))
        if not cctxt.can_send_version('3.3'):
            msg_args.pop('volume')
        return cctxt.call(ctxt, 'attach_volume', **msg_args)

    def detach_volume(self, ctxt, volume, attachment_id):
        msg_args = {'volume_id': volume.id,
                    'attachment_id': attachment_id,
                    'volume': volume}
        cctxt = self._get_cctxt(volume.service_topic_queue, ('3.4', '3.0'))
        if not self.client.can_send_version('3.4'):
            msg_args.pop('volume')
        return cctxt.call(ctxt, 'detach_volume', **msg_args)

    def copy_volume_to_image(self, ctxt, volume, image_meta):
        cctxt = self._get_cctxt(volume.service_topic_queue)
        cctxt.cast(ctxt, 'copy_volume_to_image', volume_id=volume['id'],
                   image_meta=image_meta)

    def initialize_connection(self, ctxt, volume, connector):
        cctxt = self._get_cctxt(volume.service_topic_queue)
        return cctxt.call(ctxt, 'initialize_connection', connector=connector,
                          volume=volume)

    def terminate_connection(self, ctxt, volume, connector, force=False):
        cctxt = self._get_cctxt(volume.service_topic_queue)
        return cctxt.call(ctxt, 'terminate_connection', volume_id=volume['id'],
                          connector=connector, force=force)

    def remove_export(self, ctxt, volume):
        cctxt = self._get_cctxt(volume.service_topic_queue)
        cctxt.cast(ctxt, 'remove_export', volume_id=volume['id'])

    def publish_service_capabilities(self, ctxt):
        cctxt = self._get_cctxt(fanout=True)
        cctxt.cast(ctxt, 'publish_service_capabilities')

    def accept_transfer(self, ctxt, volume, new_user, new_project,
                        no_snapshots=False):
        msg_args = {'volume_id': volume['id'],
                    'new_user': new_user,
                    'new_project': new_project,
                    'no_snapshots': no_snapshots
                    }
        cctxt = self._get_cctxt(volume.service_topic_queue, ('3.16', '3.0'))
        if not self.client.can_send_version('3.16'):
            msg_args.pop('no_snapshots')
        return cctxt.call(ctxt, 'accept_transfer', **msg_args)

    def extend_volume(self, ctxt, volume, new_size, reservations):
        cctxt = self._get_cctxt(volume.service_topic_queue)
        cctxt.cast(ctxt, 'extend_volume', volume=volume, new_size=new_size,
                   reservations=reservations)

    def migrate_volume(self, ctxt, volume, dest_backend, force_host_copy):
        backend_p = {'host': dest_backend.host,
                     'cluster_name': dest_backend.cluster_name,
                     'capabilities': dest_backend.capabilities}

        version = '3.5'
        if not self.client.can_send_version(version):
            version = '3.0'
            del backend_p['cluster_name']

        cctxt = self._get_cctxt(volume.service_topic_queue, version)
        cctxt.cast(ctxt, 'migrate_volume', volume=volume, host=backend_p,
                   force_host_copy=force_host_copy)

    def migrate_volume_completion(self, ctxt, volume, new_volume, error):
        cctxt = self._get_cctxt(volume.service_topic_queue)
        return cctxt.call(ctxt, 'migrate_volume_completion', volume=volume,
                          new_volume=new_volume, error=error,)

    def retype(self, ctxt, volume, new_type_id, dest_backend,
               migration_policy='never', reservations=None,
               old_reservations=None):
        backend_p = {'host': dest_backend.host,
                     'cluster_name': dest_backend.cluster_name,
                     'capabilities': dest_backend.capabilities}
        version = '3.5'
        if not self.client.can_send_version(version):
            version = '3.0'
            del backend_p['cluster_name']

        cctxt = self._get_cctxt(volume.service_topic_queue, version)
        cctxt.cast(ctxt, 'retype', volume=volume, new_type_id=new_type_id,
                   host=backend_p, migration_policy=migration_policy,
                   reservations=reservations,
                   old_reservations=old_reservations)

    def manage_existing(self, ctxt, volume, ref):
        cctxt = self._get_cctxt(volume.service_topic_queue)
        cctxt.cast(ctxt, 'manage_existing', ref=ref, volume=volume)

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        cctxt = self._get_cctxt(new_volume.service_topic_queue)
        cctxt.call(ctxt, 'update_migrated_volume',
                   volume=volume,
                   new_volume=new_volume,
                   volume_status=original_volume_status)

    def freeze_host(self, ctxt, service):
        """Set backend host to frozen."""
        cctxt = self._get_cctxt(service.service_topic_queue)
        return cctxt.call(ctxt, 'freeze_host')

    def thaw_host(self, ctxt, service):
        """Clear the frozen setting on a backend host."""
        cctxt = self._get_cctxt(service.service_topic_queue)
        return cctxt.call(ctxt, 'thaw_host')

    def failover(self, ctxt, service, secondary_backend_id=None):
        """Failover host to the specified backend_id (secondary). """
        version = '3.8'
        method = 'failover'
        if not self.client.can_send_version(version):
            version = '3.0'
            method = 'failover_host'
        cctxt = self._get_cctxt(service.service_topic_queue, version)
        cctxt.cast(ctxt, method, secondary_backend_id=secondary_backend_id)

    def failover_completed(self, ctxt, service, updates):
        """Complete failover on all services of the cluster."""
        cctxt = self._get_cctxt(service.service_topic_queue, '3.8',
                                fanout=True)
        cctxt.cast(ctxt, 'failover_completed', updates=updates)

    def manage_existing_snapshot(self, ctxt, snapshot, ref, backend):
        cctxt = self._get_cctxt(backend)
        cctxt.cast(ctxt, 'manage_existing_snapshot',
                   snapshot=snapshot,
                   ref=ref)

    def get_capabilities(self, ctxt, backend_id, discover):
        cctxt = self._get_cctxt(backend_id)
        return cctxt.call(ctxt, 'get_capabilities', discover=discover)

    def get_backup_device(self, ctxt, backup, volume):
        cctxt = self._get_cctxt(volume.service_topic_queue, ('3.2', '3.0'))
        if cctxt.can_send_version('3.2'):
            backup_obj = cctxt.call(ctxt, 'get_backup_device', backup=backup,
                                    want_objects=True)
        else:
            backup_dict = cctxt.call(ctxt, 'get_backup_device', backup=backup)
            backup_obj = objects.BackupDeviceInfo.from_primitive(backup_dict,
                                                                 ctxt)
        return backup_obj

    def secure_file_operations_enabled(self, ctxt, volume):
        cctxt = self._get_cctxt(volume.service_topic_queue)
        return cctxt.call(ctxt, 'secure_file_operations_enabled',
                          volume=volume)

    def get_manageable_volumes(self, ctxt, service, marker, limit, offset,
                               sort_keys, sort_dirs):
        version = ('3.10', '3.0')
        cctxt = self._get_cctxt(service.service_topic_queue, version=version)

        msg_args = {'marker': marker,
                    'limit': limit,
                    'offset': offset,
                    'sort_keys': sort_keys,
                    'sort_dirs': sort_dirs,
                    }

        if cctxt.can_send_version('3.10'):
            msg_args['want_objects'] = True

        return cctxt.call(ctxt, 'get_manageable_volumes', **msg_args)

    def get_manageable_snapshots(self, ctxt, service, marker, limit, offset,
                                 sort_keys, sort_dirs):
        version = ('3.10', '3.0')
        cctxt = self._get_cctxt(service.service_topic_queue, version=version)

        msg_args = {'marker': marker,
                    'limit': limit,
                    'offset': offset,
                    'sort_keys': sort_keys,
                    'sort_dirs': sort_dirs,
                    }

        if cctxt.can_send_version('3.10'):
            msg_args['want_objects'] = True

        return cctxt.call(ctxt, 'get_manageable_snapshots', **msg_args)

    def create_group(self, ctxt, group):
        cctxt = self._get_cctxt(group.service_topic_queue)
        cctxt.cast(ctxt, 'create_group', group=group)

    def delete_group(self, ctxt, group):
        cctxt = self._get_cctxt(group.service_topic_queue)
        cctxt.cast(ctxt, 'delete_group', group=group)

    def update_group(self, ctxt, group, add_volumes=None, remove_volumes=None):
        cctxt = self._get_cctxt(group.service_topic_queue)
        cctxt.cast(ctxt, 'update_group', group=group, add_volumes=add_volumes,
                   remove_volumes=remove_volumes)

    def create_group_from_src(self, ctxt, group, group_snapshot=None,
                              source_group=None):
        cctxt = self._get_cctxt(group.service_topic_queue)
        cctxt.cast(ctxt, 'create_group_from_src', group=group,
                   group_snapshot=group_snapshot, source_group=source_group)

    def create_group_snapshot(self, ctxt, group_snapshot):
        cctxt = self._get_cctxt(group_snapshot.service_topic_queue)
        cctxt.cast(ctxt, 'create_group_snapshot',
                   group_snapshot=group_snapshot)

    def delete_group_snapshot(self, ctxt, group_snapshot):
        cctxt = self._get_cctxt(group_snapshot.service_topic_queue)
        cctxt.cast(ctxt, 'delete_group_snapshot',
                   group_snapshot=group_snapshot)

    @rpc.assert_min_rpc_version('3.13')
    def initialize_connection_snapshot(self, ctxt, snapshot, connector):
        cctxt = self._get_cctxt(snapshot.service_topic_queue, version='3.13')
        return cctxt.call(ctxt, 'initialize_connection_snapshot',
                          snapshot_id=snapshot.id,
                          connector=connector)

    @rpc.assert_min_rpc_version('3.13')
    def terminate_connection_snapshot(self, ctxt, snapshot, connector,
                                      force=False):
        cctxt = self._get_cctxt(snapshot.service_topic_queue, version='3.13')
        return cctxt.call(ctxt, 'terminate_connection_snapshot',
                          snapshot_id=snapshot.id,
                          connector=connector, force=force)

    @rpc.assert_min_rpc_version('3.13')
    def remove_export_snapshot(self, ctxt, snapshot):
        cctxt = self._get_cctxt(snapshot.service_topic_queue, version='3.13')
        cctxt.cast(ctxt, 'remove_export_snapshot', snapshot_id=snapshot.id)

    @rpc.assert_min_rpc_version('3.9')
    def attachment_update(self, ctxt, vref, connector, attachment_id):
        version = self._compat_ver('3.9')
        cctxt = self._get_cctxt(vref.service_topic_queue, version=version)
        return cctxt.call(ctxt,
                          'attachment_update',
                          vref=vref,
                          connector=connector,
                          attachment_id=attachment_id)

    @rpc.assert_min_rpc_version('3.9')
    def attachment_delete(self, ctxt, attachment_id, vref):
        version = self._compat_ver('3.9')
        cctxt = self._get_cctxt(vref.service_topic_queue, version=version)
        return cctxt.call(ctxt,
                          'attachment_delete',
                          attachment_id=attachment_id,
                          vref=vref)

    @rpc.assert_min_rpc_version('3.7')
    def do_cleanup(self, ctxt, cleanup_request):
        """Perform this service/cluster resource cleanup as requested."""
        destination = cleanup_request.service_topic_queue
        cctxt = self._get_cctxt(destination, '3.7')
        # NOTE(geguileo): This call goes to do_cleanup code in
        # cinder.manager.CleanableManager unless in the future we overwrite it
        # in cinder.volume.manager
        cctxt.cast(ctxt, 'do_cleanup', cleanup_request=cleanup_request)

    @rpc.assert_min_rpc_version('3.12')
    def set_log_levels(self, context, service, log_request):
        cctxt = self._get_cctxt(host=service.host, version='3.12')
        cctxt.cast(context, 'set_log_levels', log_request=log_request)

    @rpc.assert_min_rpc_version('3.12')
    def get_log_levels(self, context, service, log_request):
        cctxt = self._get_cctxt(host=service.host, version='3.12')
        return cctxt.call(context, 'get_log_levels', log_request=log_request)

    @rpc.assert_min_rpc_version('3.14')
    def enable_replication(self, ctxt, group):
        cctxt = self._get_cctxt(group.service_topic_queue, version='3.14')
        cctxt.cast(ctxt, 'enable_replication',
                   group=group)

    @rpc.assert_min_rpc_version('3.14')
    def disable_replication(self, ctxt, group):
        cctxt = self._get_cctxt(group.service_topic_queue, version='3.14')
        cctxt.cast(ctxt, 'disable_replication',
                   group=group)

    @rpc.assert_min_rpc_version('3.14')
    def failover_replication(self, ctxt, group, allow_attached_volume=False,
                             secondary_backend_id=None):
        cctxt = self._get_cctxt(group.service_topic_queue, version='3.14')
        cctxt.cast(ctxt, 'failover_replication',
                   group=group, allow_attached_volume=allow_attached_volume,
                   secondary_backend_id=secondary_backend_id)

    @rpc.assert_min_rpc_version('3.14')
    def list_replication_targets(self, ctxt, group):
        cctxt = self._get_cctxt(group.service_topic_queue, version='3.14')
        return cctxt.call(ctxt, 'list_replication_targets',
                          group=group)
