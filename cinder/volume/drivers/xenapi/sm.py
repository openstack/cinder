# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
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

from cinder import flags
from cinder.openstack.common import cfg
from cinder.volume import driver
from cinder.volume.drivers.xenapi import lib as xenapi_lib


xenapi_opts = [
    cfg.StrOpt('xenapi_connection_url',
               default=None,
               help='URL for XenAPI connection'),
    cfg.StrOpt('xenapi_connection_username',
               default='root',
               help='Username for XenAPI connection'),
    cfg.StrOpt('xenapi_connection_password',
               default=None,
               help='Password for XenAPI connection'),
]

xenapi_nfs_opts = [
    cfg.StrOpt('xenapi_nfs_server',
               default=None,
               help='NFS server to be used by XenAPINFSDriver'),
    cfg.StrOpt('xenapi_nfs_serverpath',
               default=None,
               help='Path of exported NFS, used by XenAPINFSDriver'),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(xenapi_opts)
FLAGS.register_opts(xenapi_nfs_opts)


class XenAPINFSDriver(driver.VolumeDriver):

    def do_setup(self, context):
        session_factory = xenapi_lib.SessionFactory(
            FLAGS.xenapi_connection_url,
            FLAGS.xenapi_connection_username,
            FLAGS.xenapi_connection_password
        )
        self.nfs_ops = xenapi_lib.NFSBasedVolumeOperations(session_factory)

    def create_cloned_volume(self, volume, src_vref):
        raise NotImplementedError()

    def create_volume(self, volume):
        volume_details = self.nfs_ops.create_volume(
            FLAGS.xenapi_nfs_server,
            FLAGS.xenapi_nfs_serverpath,
            volume['size'],
            volume['display_name'],
            volume['display_description']
        )
        location = "%(sr_uuid)s/%(vdi_uuid)s" % volume_details
        return dict(provider_location=location)

    def create_export(self, context, volume):
        pass

    def delete_volume(self, volume):
        sr_uuid, vdi_uuid = volume['provider_location'].split('/')

        self.nfs_ops.delete_volume(
            FLAGS.xenapi_nfs_server,
            FLAGS.xenapi_nfs_serverpath,
            sr_uuid,
            vdi_uuid
        )

    def remove_export(self, context, volume):
        pass

    def initialize_connection(self, volume, connector):
        sr_uuid, vdi_uuid = volume['provider_location'].split('/')

        return dict(
            driver_volume_type='xensm',
            data=dict(
                name_label=volume['display_name'] or '',
                name_description=volume['display_description'] or '',
                sr_uuid=sr_uuid,
                vdi_uuid=vdi_uuid,
                sr_type='nfs',
                server=FLAGS.xenapi_nfs_server,
                serverpath=FLAGS.xenapi_nfs_serverpath,
                introduce_sr_keys=['sr_type', 'server', 'serverpath']
            )
        )

    def terminate_connection(self, volume, connector, force=False, **kwargs):
        pass

    def check_for_setup_error(self):
        """To override superclass' method"""

    def create_volume_from_snapshot(self, volume, snapshot):
        raise NotImplementedError()

    def create_snapshot(self, snapshot):
        raise NotImplementedError()

    def delete_snapshot(self, snapshot):
        raise NotImplementedError()

    def ensure_export(self, context, volume):
        pass

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        raise NotImplementedError()

    def copy_volume_to_image(self, context, volume, image_service, image_id):
        raise NotImplementedError()
