#    Copyright 2012 OpenStack LLC
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

from cinder import exception
from cinder import flags
from cinder.openstack.common import log as logging
from cinder.volume import driver


LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS


class SheepdogDriver(driver.VolumeDriver):
    """Executes commands relating to Sheepdog Volumes"""

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met"""
        try:
            #NOTE(francois-charlier) Since 0.24 'collie cluster info -r'
            #  gives short output, but for compatibility reason we won't
            #  use it and just check if 'running' is in the output.
            (out, err) = self._execute('collie', 'cluster', 'info')
            if 'running' not in out.split():
                exception_message = (_("Sheepdog is not working: %s") % out)
                raise exception.VolumeBackendAPIException(
                    data=exception_message)

        except exception.ProcessExecutionError:
            exception_message = _("Sheepdog is not working")
            raise exception.VolumeBackendAPIException(data=exception_message)

    def create_cloned_volume(self, volume, src_vref):
        raise NotImplementedError()

    def create_volume(self, volume):
        """Creates a sheepdog volume"""
        self._try_execute('qemu-img', 'create',
                          "sheepdog:%s" % volume['name'],
                          '%sG' % volume['size'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a sheepdog volume from a snapshot."""
        self._try_execute('qemu-img', 'create', '-b',
                          "sheepdog:%s:%s" % (snapshot['volume_name'],
                                              snapshot['name']),
                          "sheepdog:%s" % volume['name'])

    def delete_volume(self, volume):
        """Deletes a logical volume"""
        self._try_execute('collie', 'vdi', 'delete', volume['name'])

    def create_snapshot(self, snapshot):
        """Creates a sheepdog snapshot"""
        self._try_execute('qemu-img', 'snapshot', '-c', snapshot['name'],
                          "sheepdog:%s" % snapshot['volume_name'])

    def delete_snapshot(self, snapshot):
        """Deletes a sheepdog snapshot"""
        self._try_execute('collie', 'vdi', 'delete', snapshot['volume_name'],
                          '-s', snapshot['name'])

    def local_path(self, volume):
        return "sheepdog:%s" % volume['name']

    def ensure_export(self, context, volume):
        """Safely and synchronously recreates an export for a logical volume"""
        pass

    def create_export(self, context, volume):
        """Exports the volume"""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume"""
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
