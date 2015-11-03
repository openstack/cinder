# Copyright (c) 2013 Mirantis, Inc.
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

import os

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils
from oslo_utils import units

from cinder import context
from cinder.db.sqlalchemy import api
from cinder import exception
from cinder.i18n import _, _LI
from cinder.image import image_utils
from cinder.volume import driver
from cinder.volume import utils as volutils


LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.ListOpt('available_devices',
                default=[],
                help='List of all available devices'),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)


class BlockDeviceDriver(driver.BaseVD, driver.LocalVD,
                        driver.CloneableImageVD, driver.TransferVD):
    VERSION = '2.1.0'

    def __init__(self, *args, **kwargs):
        super(BlockDeviceDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(volume_opts)
        self.backend_name = \
            self.configuration.safe_get('volume_backend_name') or "BlockDev"
        target_driver =\
            self.target_mapping[self.configuration.safe_get('iscsi_helper')]
        self.target_driver = importutils.import_object(
            target_driver,
            configuration=self.configuration,
            db=self.db,
            executor=self._execute)

    def check_for_setup_error(self):
        pass

    def create_volume(self, volume):
        device = self.find_appropriate_size_device(volume['size'])
        LOG.info(_LI("Create %(volume)s on %(device)s"),
                 {"volume": volume['name'], "device": device})
        return {
            'provider_location': device,
        }

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        dev_path = self.local_path(volume)
        if not dev_path or dev_path not in \
                self.configuration.available_devices:
            return
        if os.path.exists(dev_path) and \
                self.configuration.volume_clear != 'none':
            dev_size = self._get_devices_sizes([dev_path])
            volutils.clear_volume(
                dev_size[dev_path], dev_path,
                volume_clear=self.configuration.volume_clear,
                volume_clear_size=self.configuration.volume_clear_size)

    def local_path(self, device):
        if device['provider_location']:
            path = device['provider_location'].rsplit(" ", 1)
            return path[-1]
        else:
            return None

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        image_utils.fetch_to_raw(context,
                                 image_service,
                                 image_id,
                                 self.local_path(volume),
                                 self.configuration.volume_dd_blocksize,
                                 size=volume['size'])

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        image_utils.upload_volume(context,
                                  image_service,
                                  image_meta,
                                  self.local_path(volume))

    def create_cloned_volume(self, volume, src_vref):
        LOG.info(_LI('Creating clone of volume: %s'), src_vref['id'])
        device = self.find_appropriate_size_device(src_vref['size'])
        dev_size = self._get_devices_sizes([device])
        volutils.copy_volume(
            self.local_path(src_vref), device,
            dev_size[device],
            self.configuration.volume_dd_blocksize,
            execute=self._execute)
        return {
            'provider_location': device,
        }

    def get_volume_stats(self, refresh=False):
        if refresh:
            self._update_volume_stats()
        return self._stats

    def _update_volume_stats(self):
        """Retrieve stats info from volume group."""
        dict_of_devices_sizes = self._devices_sizes()
        used_devices = self._get_used_devices()
        total_size = 0
        free_size = 0
        for device, size in dict_of_devices_sizes.items():
            if device not in used_devices:
                free_size += size
            total_size += size

        LOG.debug("Updating volume stats")
        backend_name = self.configuration.safe_get('volume_backend_name')
        data = {'total_capacity_gb': total_size / units.Ki,
                'free_capacity_gb': free_size / units.Ki,
                'reserved_percentage': self.configuration.reserved_percentage,
                'QoS_support': False,
                'volume_backend_name': backend_name or self.__class__.__name__,
                'vendor_name': "Open Source",
                'driver_version': self.VERSION,
                'storage_protocol': 'unknown'}

        self._stats = data

    def _get_used_devices(self):
        lst = api.volume_get_all_by_host(context.get_admin_context(),
                                         self.host)
        used_devices = set()
        for volume in lst:
            local_path = self.local_path(volume)
            if local_path:
                used_devices.add(local_path)
        return used_devices

    def _get_devices_sizes(self, dev_paths):
        """Return devices' sizes in Mb"""
        out, _err = self._execute('blockdev', '--getsize64', *dev_paths,
                                  run_as_root=True)
        dev_sizes = {}
        out = out.split('\n')
        # blockdev returns devices' sizes in order that
        # they have been passed to it.
        for n, size in enumerate(out[:-1]):
            dev_sizes[dev_paths[n]] = int(size) / units.Mi

        return dev_sizes

    def _devices_sizes(self):
        available_devices = self.configuration.available_devices
        return self._get_devices_sizes(available_devices)

    def find_appropriate_size_device(self, size):
        dict_of_devices_sizes = self._devices_sizes()
        free_devices = (set(self.configuration.available_devices) -
                        self._get_used_devices())
        if not free_devices:
            raise exception.CinderException(_("No free disk"))
        possible_device = None
        possible_device_size = None
        for device in free_devices:
            dev_size = dict_of_devices_sizes[device]
            if (size * units.Ki <= dev_size and
                    (possible_device is None or
                     dev_size < possible_device_size)):
                possible_device = device
                possible_device_size = dev_size

        if possible_device:
            return possible_device
        else:
            raise exception.CinderException(_("No big enough free disk"))

    def extend_volume(self, volume, new_size):
        dev_path = self.local_path(volume)
        total_size = self._get_devices_sizes([dev_path])
        # Convert from Megabytes to Gigabytes
        size = total_size[dev_path] / units.Ki
        if size < new_size:
            msg = _("Insufficient free space available to extend volume.")
            LOG.error(msg, resource=volume)
            raise exception.CinderException(msg)

    # #######  Interface methods for DataPath (Target Driver) ########

    def ensure_export(self, context, volume):
        volume_path = self.local_path(volume)
        model_update = \
            self.target_driver.ensure_export(
                context,
                volume,
                volume_path)
        return model_update

    def create_export(self, context, volume, connector):
        volume_path = self.local_path(volume)
        export_info = self.target_driver.create_export(context,
                                                       volume,
                                                       volume_path)
        return {
            'provider_location': export_info['location'] + ' ' + volume_path,
            'provider_auth': export_info['auth'],
        }

    def remove_export(self, context, volume):
        self.target_driver.remove_export(context, volume)

    def initialize_connection(self, volume, connector):
        if connector['host'] != volutils.extract_host(volume['host'], 'host'):
            return self.target_driver.initialize_connection(volume, connector)
        else:
            return {
                'driver_volume_type': 'local',
                'data': {'device_path': self.local_path(volume)},
            }

    def validate_connector(self, connector):
        return self.target_driver.validate_connector(connector)

    def terminate_connection(self, volume, connector, **kwargs):
        pass
