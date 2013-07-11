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

from oslo.config import cfg

from cinder import exception
from cinder.image import glance
from cinder.image import image_utils
from cinder.openstack.common import log as logging
from cinder.volume import driver
from cinder.volume.drivers.xenapi import lib as xenapi_lib

LOG = logging.getLogger(__name__)

xenapi_opts = [
    cfg.StrOpt('xenapi_connection_url',
               default=None,
               help='URL for XenAPI connection'),
    cfg.StrOpt('xenapi_connection_username',
               default='root',
               help='Username for XenAPI connection'),
    cfg.StrOpt('xenapi_connection_password',
               default=None,
               help='Password for XenAPI connection',
               secret=True),
    cfg.StrOpt('xenapi_sr_base_path',
               default='/var/run/sr-mount',
               help='Base path to the storage repository'),
]

xenapi_nfs_opts = [
    cfg.StrOpt('xenapi_nfs_server',
               default=None,
               help='NFS server to be used by XenAPINFSDriver'),
    cfg.StrOpt('xenapi_nfs_serverpath',
               default=None,
               help='Path of exported NFS, used by XenAPINFSDriver'),
]

CONF = cfg.CONF
CONF.register_opts(xenapi_opts)
CONF.register_opts(xenapi_nfs_opts)


class XenAPINFSDriver(driver.VolumeDriver):
    def __init__(self, *args, **kwargs):
        super(XenAPINFSDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(xenapi_opts)
        self.configuration.append_config_values(xenapi_nfs_opts)

    def do_setup(self, context):
        session_factory = xenapi_lib.SessionFactory(
            self.configuration.xenapi_connection_url,
            self.configuration.xenapi_connection_username,
            self.configuration.xenapi_connection_password
        )
        self.nfs_ops = xenapi_lib.NFSBasedVolumeOperations(session_factory)

    def create_cloned_volume(self, volume, src_vref):
        raise NotImplementedError()

    def create_volume(self, volume):
        volume_details = self.nfs_ops.create_volume(
            self.configuration.xenapi_nfs_server,
            self.configuration.xenapi_nfs_serverpath,
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
            self.configuration.xenapi_nfs_server,
            self.configuration.xenapi_nfs_serverpath,
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
                server=self.configuration.xenapi_nfs_server,
                serverpath=self.configuration.xenapi_nfs_serverpath,
                introduce_sr_keys=['sr_type', 'server', 'serverpath']
            )
        )

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def check_for_setup_error(self):
        """To override superclass' method"""

    def create_volume_from_snapshot(self, volume, snapshot):
        return self._copy_volume(
            snapshot, volume['display_name'], volume['name_description'])

    def create_snapshot(self, snapshot):
        volume_id = snapshot['volume_id']
        volume = snapshot['volume']
        return self._copy_volume(
            volume, snapshot['display_name'], snapshot['display_description'])

    def _copy_volume(self, volume, target_name, target_desc):
        sr_uuid, vdi_uuid = volume['provider_location'].split('/')

        volume_details = self.nfs_ops.copy_volume(
            self.configuration.xenapi_nfs_server,
            self.configuration.xenapi_nfs_serverpath,
            sr_uuid,
            vdi_uuid,
            target_name,
            target_desc
        )
        location = "%(sr_uuid)s/%(vdi_uuid)s" % volume_details
        return dict(provider_location=location)

    def delete_snapshot(self, snapshot):
        self.delete_volume(snapshot)

    def ensure_export(self, context, volume):
        pass

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        if image_utils.is_xenserver_image(context, image_service, image_id):
            return self._use_glance_plugin_to_copy_image_to_volume(
                context, volume, image_service, image_id)

        return self._use_image_utils_to_pipe_bytes_to_volume(
            context, volume, image_service, image_id)

    def _use_image_utils_to_pipe_bytes_to_volume(self, context, volume,
                                                 image_service, image_id):
        sr_uuid, vdi_uuid = volume['provider_location'].split('/')
        with self.nfs_ops.volume_attached_here(CONF.xenapi_nfs_server,
                                               CONF.xenapi_nfs_serverpath,
                                               sr_uuid, vdi_uuid,
                                               False) as device:
            image_utils.fetch_to_raw(context,
                                     image_service,
                                     image_id,
                                     device)

    def _use_glance_plugin_to_copy_image_to_volume(self, context, volume,
                                                   image_service, image_id):
        sr_uuid, vdi_uuid = volume['provider_location'].split('/')

        api_servers = glance.get_api_servers()
        glance_server = api_servers.next()
        auth_token = context.auth_token

        overwrite_result = self.nfs_ops.use_glance_plugin_to_overwrite_volume(
            CONF.xenapi_nfs_server,
            CONF.xenapi_nfs_serverpath,
            sr_uuid,
            vdi_uuid,
            glance_server,
            image_id,
            auth_token,
            CONF.xenapi_sr_base_path)

        if overwrite_result is False:
            raise exception.ImageCopyFailure(reason='Overwriting volume '
                                                    'failed.')

        self.nfs_ops.resize_volume(
            CONF.xenapi_nfs_server,
            CONF.xenapi_nfs_serverpath,
            sr_uuid,
            vdi_uuid,
            volume['size'])

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        if image_utils.is_xenserver_format(image_meta):
            return self._use_glance_plugin_to_upload_volume(
                context, volume, image_service, image_meta)

        return self._use_image_utils_to_upload_volume(
            context, volume, image_service, image_meta)

    def _use_image_utils_to_upload_volume(self, context, volume, image_service,
                                          image_meta):
        sr_uuid, vdi_uuid = volume['provider_location'].split('/')
        with self.nfs_ops.volume_attached_here(CONF.xenapi_nfs_server,
                                               CONF.xenapi_nfs_serverpath,
                                               sr_uuid, vdi_uuid,
                                               True) as device:
            image_utils.upload_volume(context,
                                      image_service,
                                      image_meta,
                                      device)

    def _use_glance_plugin_to_upload_volume(self, context, volume,
                                            image_service, image_meta):
        image_id = image_meta['id']

        sr_uuid, vdi_uuid = volume['provider_location'].split('/')

        api_servers = glance.get_api_servers()
        glance_server = api_servers.next()
        auth_token = context.auth_token

        self.nfs_ops.use_glance_plugin_to_upload_volume(
            CONF.xenapi_nfs_server,
            CONF.xenapi_nfs_serverpath,
            sr_uuid,
            vdi_uuid,
            glance_server,
            image_id,
            auth_token,
            CONF.xenapi_sr_base_path)

    def get_volume_stats(self, refresh=False):
        if refresh or not self._stats:
            data = {}

            backend_name = self.configuration.safe_get('volume_backend_name')
            data["volume_backend_name"] = backend_name or 'XenAPINFS',
            data['vendor_name'] = 'Open Source',
            data['driver_version'] = '1.0'
            data['storage_protocol'] = 'xensm'
            data['total_capacity_gb'] = 'unknown'
            data['free_capacity_gb'] = 'unknown'
            data['reserved_percentage'] = 0
            self._stats = data

        return self._stats
