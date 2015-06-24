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
import oslo_messaging as messaging
from oslo_serialization import jsonutils

from cinder.objects import base as objects_base
from cinder import rpc
from cinder.volume import utils


CONF = cfg.CONF


class VolumeAPI(object):
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
    """

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, topic=None):
        super(VolumeAPI, self).__init__()
        target = messaging.Target(topic=CONF.volume_topic,
                                  version=self.BASE_RPC_API_VERSION)
        serializer = objects_base.CinderObjectSerializer()
        self.client = rpc.get_client(target, '1.31', serializer=serializer)

    def create_consistencygroup(self, ctxt, group, host):
        new_host = utils.extract_host(host)
        cctxt = self.client.prepare(server=new_host, version='1.26')
        cctxt.cast(ctxt, 'create_consistencygroup',
                   group=group)

    def delete_consistencygroup(self, ctxt, group):
        host = utils.extract_host(group.host)
        cctxt = self.client.prepare(server=host, version='1.26')
        cctxt.cast(ctxt, 'delete_consistencygroup',
                   group=group)

    def update_consistencygroup(self, ctxt, group, add_volumes=None,
                                remove_volumes=None):
        host = utils.extract_host(group.host)
        cctxt = self.client.prepare(server=host, version='1.26')
        cctxt.cast(ctxt, 'update_consistencygroup',
                   group=group,
                   add_volumes=add_volumes,
                   remove_volumes=remove_volumes)

    def create_consistencygroup_from_src(self, ctxt, group, cgsnapshot=None,
                                         source_cg=None):
        new_host = utils.extract_host(group.host)
        cctxt = self.client.prepare(server=new_host, version='1.31')
        cctxt.cast(ctxt, 'create_consistencygroup_from_src',
                   group=group,
                   cgsnapshot=cgsnapshot,
                   source_cg=source_cg)

    def create_cgsnapshot(self, ctxt, cgsnapshot):
        host = utils.extract_host(cgsnapshot.consistencygroup.host)
        cctxt = self.client.prepare(server=host, version='1.31')
        cctxt.cast(ctxt, 'create_cgsnapshot', cgsnapshot=cgsnapshot)

    def delete_cgsnapshot(self, ctxt, cgsnapshot):
        new_host = utils.extract_host(cgsnapshot.consistencygroup.host)
        cctxt = self.client.prepare(server=new_host, version='1.31')
        cctxt.cast(ctxt, 'delete_cgsnapshot', cgsnapshot=cgsnapshot)

    def create_volume(self, ctxt, volume, host, request_spec,
                      filter_properties, allow_reschedule=True):
        new_host = utils.extract_host(host)
        cctxt = self.client.prepare(server=new_host, version='1.24')
        request_spec_p = jsonutils.to_primitive(request_spec)
        cctxt.cast(ctxt, 'create_volume',
                   volume_id=volume['id'],
                   request_spec=request_spec_p,
                   filter_properties=filter_properties,
                   allow_reschedule=allow_reschedule)

    def delete_volume(self, ctxt, volume, unmanage_only=False):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.15')
        cctxt.cast(ctxt, 'delete_volume',
                   volume_id=volume['id'],
                   unmanage_only=unmanage_only)

    def create_snapshot(self, ctxt, volume, snapshot):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host)
        cctxt.cast(ctxt, 'create_snapshot', volume_id=volume['id'],
                   snapshot=snapshot)

    def delete_snapshot(self, ctxt, snapshot, host, unmanage_only=False):
        new_host = utils.extract_host(host)
        cctxt = self.client.prepare(server=new_host)
        cctxt.cast(ctxt, 'delete_snapshot', snapshot=snapshot,
                   unmanage_only=unmanage_only)

    def attach_volume(self, ctxt, volume, instance_uuid, host_name,
                      mountpoint, mode):

        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.11')
        return cctxt.call(ctxt, 'attach_volume',
                          volume_id=volume['id'],
                          instance_uuid=instance_uuid,
                          host_name=host_name,
                          mountpoint=mountpoint,
                          mode=mode)

    def detach_volume(self, ctxt, volume, attachment_id):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.20')
        return cctxt.call(ctxt, 'detach_volume', volume_id=volume['id'],
                          attachment_id=attachment_id)

    def copy_volume_to_image(self, ctxt, volume, image_meta):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.3')
        cctxt.cast(ctxt, 'copy_volume_to_image', volume_id=volume['id'],
                   image_meta=image_meta)

    def initialize_connection(self, ctxt, volume, connector):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host)
        return cctxt.call(ctxt, 'initialize_connection',
                          volume_id=volume['id'],
                          connector=connector)

    def terminate_connection(self, ctxt, volume, connector, force=False):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host)
        return cctxt.call(ctxt, 'terminate_connection', volume_id=volume['id'],
                          connector=connector, force=force)

    def remove_export(self, ctxt, volume):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.30')
        cctxt.cast(ctxt, 'remove_export', volume_id=volume['id'])

    def publish_service_capabilities(self, ctxt):
        cctxt = self.client.prepare(fanout=True, version='1.2')
        cctxt.cast(ctxt, 'publish_service_capabilities')

    def accept_transfer(self, ctxt, volume, new_user, new_project):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.9')
        return cctxt.call(ctxt, 'accept_transfer', volume_id=volume['id'],
                          new_user=new_user, new_project=new_project)

    def extend_volume(self, ctxt, volume, new_size, reservations):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.14')
        cctxt.cast(ctxt, 'extend_volume', volume_id=volume['id'],
                   new_size=new_size, reservations=reservations)

    def migrate_volume(self, ctxt, volume, dest_host, force_host_copy):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.8')
        host_p = {'host': dest_host.host,
                  'capabilities': dest_host.capabilities}
        cctxt.cast(ctxt, 'migrate_volume', volume_id=volume['id'],
                   host=host_p, force_host_copy=force_host_copy)

    def migrate_volume_completion(self, ctxt, volume, new_volume, error):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.10')
        return cctxt.call(ctxt, 'migrate_volume_completion',
                          volume_id=volume['id'],
                          new_volume_id=new_volume['id'],
                          error=error)

    def retype(self, ctxt, volume, new_type_id, dest_host,
               migration_policy='never', reservations=None):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.12')
        host_p = {'host': dest_host.host,
                  'capabilities': dest_host.capabilities}
        cctxt.cast(ctxt, 'retype', volume_id=volume['id'],
                   new_type_id=new_type_id, host=host_p,
                   migration_policy=migration_policy,
                   reservations=reservations)

    def manage_existing(self, ctxt, volume, ref):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.15')
        cctxt.cast(ctxt, 'manage_existing', volume_id=volume['id'], ref=ref)

    def promote_replica(self, ctxt, volume):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.17')
        cctxt.cast(ctxt, 'promote_replica', volume_id=volume['id'])

    def reenable_replication(self, ctxt, volume):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.17')
        cctxt.cast(ctxt, 'reenable_replication', volume_id=volume['id'])

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        host = utils.extract_host(new_volume['host'])
        cctxt = self.client.prepare(server=host, version='1.19')
        cctxt.call(ctxt,
                   'update_migrated_volume',
                   volume=volume,
                   new_volume=new_volume,
                   volume_status=original_volume_status)

    def enable_replication(self, ctxt, volume):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.27')
        cctxt.cast(ctxt, 'enable_replication', volume=volume)

    def disable_replication(self, ctxt, volume):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.27')
        cctxt.cast(ctxt, 'disable_replication',
                   volume=volume)

    def failover_replication(self,
                             ctxt,
                             volume,
                             secondary=None):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.27')
        cctxt.cast(ctxt, 'failover_replication',
                   volume=volume,
                   secondary=secondary)

    def list_replication_targets(self, ctxt, volume):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.27')
        return cctxt.call(ctxt, 'list_replication_targets', volume=volume)

    def manage_existing_snapshot(self, ctxt, snapshot, ref, host):
        cctxt = self.client.prepare(server=host, version='1.28')
        cctxt.cast(ctxt, 'manage_existing_snapshot',
                   snapshot=snapshot,
                   ref=ref)

    def get_capabilities(self, ctxt, host, discover):
        new_host = utils.extract_host(host)
        cctxt = self.client.prepare(server=new_host, version='1.29')
        return cctxt.call(ctxt, 'get_capabilities', discover=discover)
