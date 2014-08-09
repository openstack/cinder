#    Copyright 2012 OpenStack Foundation
#    Copyright (c) 2013 Zelin.io
#    All Rights Reserved.
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
SheepDog Volume Driver.

"""
import os
import re
import tempfile

from oslo.config import cfg

from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder.openstack.common import units
from cinder.volume import driver


LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.import_opt("image_conversion_dir", "cinder.image.image_utils")


class SheepdogDriver(driver.VolumeDriver):
    """Executes commands relating to Sheepdog Volumes."""

    VERSION = "1.0.0"

    def __init__(self, *args, **kwargs):
        super(SheepdogDriver, self).__init__(*args, **kwargs)
        self.stats_pattern = re.compile(r'[\w\s%]*Total\s(\d+)\s(\d+)*')
        self._stats = {}

    def check_for_setup_error(self):
        """Return error if prerequisites aren't met."""
        try:
            #NOTE(francois-charlier) Since 0.24 'collie cluster info -r'
            #  gives short output, but for compatibility reason we won't
            #  use it and just check if 'running' is in the output.
            (out, err) = self._execute('collie', 'cluster', 'info')
            if 'status: running' not in out:
                exception_message = (_("Sheepdog is not working: %s") % out)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        except processutils.ProcessExecutionError:
            exception_message = _("Sheepdog is not working")
            raise exception.VolumeBackendAPIException(data=exception_message)

    def create_cloned_volume(self, volume, src_vref):
        raise NotImplementedError()

    def create_volume(self, volume):
        """Create a sheepdog volume."""
        self._try_execute('qemu-img', 'create',
                          "sheepdog:%s" % volume['name'],
                          '%sG' % volume['size'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a sheepdog volume from a snapshot."""
        self._try_execute('qemu-img', 'create', '-b',
                          "sheepdog:%s:%s" % (snapshot['volume_name'],
                                              snapshot['name']),
                          "sheepdog:%s" % volume['name'])

    def delete_volume(self, volume):
        """Delete a logical volume."""
        self._delete(volume)

    def _ensure_dir_exists(self, tmp_dir):
        if tmp_dir and not os.path.exists(tmp_dir):
            os.makedirs(tmp_dir)

    def _resize(self, volume, size=None):
        if not size:
            size = int(volume['size']) * units.Gi

        self._try_execute('collie', 'vdi', 'resize',
                          volume['name'], size)

    def _delete(self, volume):
        self._try_execute('collie', 'vdi', 'delete',
                          volume['name'])

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        # use the image_conversion_dir as a temporary place to save the image
        conversion_dir = CONF.image_conversion_dir
        self._ensure_dir_exists(conversion_dir)
        with tempfile.NamedTemporaryFile(dir=conversion_dir) as tmp:
            # (wenhao): we don't need to convert to raw for sheepdog.
            image_utils.fetch_verify_image(context, image_service,
                                           image_id, tmp.name)

            # remove the image created by import before this function.
            # see volume/drivers/manager.py:_create_volume
            self._delete(volume)
            # convert and store into sheepdog
            image_utils.convert_image(tmp.name, 'sheepdog:%s' % volume['name'],
                                      'raw')
            self._resize(volume)

    def create_snapshot(self, snapshot):
        """Create a sheepdog snapshot."""
        self._try_execute('qemu-img', 'snapshot', '-c', snapshot['name'],
                          "sheepdog:%s" % snapshot['volume_name'])

    def delete_snapshot(self, snapshot):
        """Delete a sheepdog snapshot."""
        self._try_execute('collie', 'vdi', 'delete', snapshot['volume_name'],
                          '-s', snapshot['name'])

    def local_path(self, volume):
        return "sheepdog:%s" % volume['name']

    def ensure_export(self, context, volume):
        """Safely and synchronously recreate an export for a logical volume."""
        pass

    def create_export(self, context, volume):
        """Export a volume."""
        pass

    def remove_export(self, context, volume):
        """Remove an export for a logical volume."""
        pass

    def initialize_connection(self, volume, connector):
        return {
            'driver_volume_type': 'sheepdog',
            'data': {
                'name': volume['name']
            }
        }

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def _update_volume_stats(self):
        stats = {}

        backend_name = "sheepdog"
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        stats["volume_backend_name"] = backend_name or 'sheepdog'
        stats['vendor_name'] = 'Open Source'
        stats['dirver_version'] = self.VERSION
        stats['storage_protocol'] = 'sheepdog'
        stats['total_capacity_gb'] = 'unknown'
        stats['free_capacity_gb'] = 'unknown'
        stats['reserved_percentage'] = 0
        stats['QoS_support'] = False

        try:
            stdout, _err = self._execute('collie', 'node', 'info', '-r')
            m = self.stats_pattern.match(stdout)
            total = float(m.group(1))
            used = float(m.group(2))
            stats['total_capacity_gb'] = total / units.Gi
            stats['free_capacity_gb'] = (total - used) / units.Gi
        except processutils.ProcessExecutionError:
            LOG.exception(_('error refreshing volume stats'))

        self._stats = stats

    def get_volume_stats(self, refresh=False):
        if refresh:
            self._update_volume_stats()
        return self._stats

    def extend_volume(self, volume, new_size):
        """Extend an Existing Volume."""
        old_size = volume['size']

        try:
            size = int(new_size) * units.Gi
            self._resize(volume, size=size)
        except Exception:
            msg = _('Failed to Extend Volume '
                    '%(volname)s') % {'volname': volume['name']}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug("Extend volume from %(old_size)s GB to %(new_size)s GB.",
                  {'old_size': old_size, 'new_size': new_size})

    def backup_volume(self, context, backup, backup_service):
        """Create a new backup from an existing volume."""
        raise NotImplementedError()

    def restore_backup(self, context, backup, volume, backup_service):
        """Restore an existing backup to a new or existing volume."""
        raise NotImplementedError()
