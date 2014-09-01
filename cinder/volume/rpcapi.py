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

from oslo.config import cfg
from oslo import messaging

from cinder.openstack.common import jsonutils
from cinder import rpc
from cinder.volume import utils


CONF = cfg.CONF


class VolumeAPI(object):
    '''Client side of the volume rpc API.

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
    '''

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, topic=None):
        super(VolumeAPI, self).__init__()
        target = messaging.Target(topic=CONF.volume_topic,
                                  version=self.BASE_RPC_API_VERSION)
        self.client = rpc.get_client(target, '1.18')

    def create_consistencygroup(self, ctxt, group, host):
        new_host = utils.extract_host(host)
        cctxt = self.client.prepare(server=new_host, version='1.18')
        cctxt.cast(ctxt, 'create_consistencygroup',
                   group_id=group['id'])

    def delete_consistencygroup(self, ctxt, group):
        host = utils.extract_host(group['host'])
        cctxt = self.client.prepare(server=host, version='1.18')
        cctxt.cast(ctxt, 'delete_consistencygroup',
                   group_id=group['id'])

    def create_cgsnapshot(self, ctxt, group, cgsnapshot):

        host = utils.extract_host(group['host'])
        cctxt = self.client.prepare(server=host, version='1.18')
        cctxt.cast(ctxt, 'create_cgsnapshot',
                   group_id=group['id'],
                   cgsnapshot_id=cgsnapshot['id'])

    def delete_cgsnapshot(self, ctxt, cgsnapshot, host):
        new_host = utils.extract_host(host)
        cctxt = self.client.prepare(server=new_host, version='1.18')
        cctxt.cast(ctxt, 'delete_cgsnapshot',
                   cgsnapshot_id=cgsnapshot['id'])

    def create_volume(self, ctxt, volume, host,
                      request_spec, filter_properties,
                      allow_reschedule=True,
                      snapshot_id=None, image_id=None,
                      source_replicaid=None,
                      source_volid=None,
                      consistencygroup_id=None):

        new_host = utils.extract_host(host)
        cctxt = self.client.prepare(server=new_host, version='1.4')
        request_spec_p = jsonutils.to_primitive(request_spec)
        cctxt.cast(ctxt, 'create_volume',
                   volume_id=volume['id'],
                   request_spec=request_spec_p,
                   filter_properties=filter_properties,
                   allow_reschedule=allow_reschedule,
                   snapshot_id=snapshot_id,
                   image_id=image_id,
                   source_replicaid=source_replicaid,
                   source_volid=source_volid,
                   consistencygroup_id=consistencygroup_id)

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
                   snapshot_id=snapshot['id'])

    def delete_snapshot(self, ctxt, snapshot, host):
        new_host = utils.extract_host(host)
        cctxt = self.client.prepare(server=new_host)
        cctxt.cast(ctxt, 'delete_snapshot', snapshot_id=snapshot['id'])

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

    def detach_volume(self, ctxt, volume):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host)
        return cctxt.call(ctxt, 'detach_volume', volume_id=volume['id'])

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

    def publish_service_capabilities(self, ctxt):
        cctxt = self.client.prepare(fanout=True, version='1.2')
        cctxt.cast(ctxt, 'publish_service_capabilities')

    def accept_transfer(self, ctxt, volume, new_user, new_project):
        new_host = utils.extract_host(volume['host'])
        cctxt = self.client.prepare(server=new_host, version='1.9')
        cctxt.cast(ctxt, 'accept_transfer', volume_id=volume['id'],
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
