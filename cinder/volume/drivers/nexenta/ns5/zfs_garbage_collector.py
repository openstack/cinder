# Copyright 2016 Nexenta Systems, Inc.
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

from cinder import exception
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class ZFSGarbageCollectorMixIn(object):
    """Collects and removes volumes and snapshots

    Collects ZFS objects such as volumes and snapshots which could not be
    removed because of dependencies. Removes them later.
    This mixin should be used with volume driver class.
    A driver must have 'nef' attribute which is instance of
    ns5.NexentaJSONProxy class
    """
    def __init__(self):
        self._needless_objects = set()

    def mark_as_garbage(self, zfs_object):
        """Puts ZFS object into list for further removal

        :param zfs_object: full path to a volume or a snapshot
        """
        self._needless_objects.add(zfs_object)

    def should_destroy_later(self, e):
        return 'Failed to destroy snapshot' in e.args[0] or (
            'must be destroyed first' in e.args[0])

    def destroy_later_or_raise(self, e, zfs_object):
        do = self.should_destroy_later(e)
        if do:
            LOG.debug('Failed to destroy ZFS object. Will do it later.')
            self.mark_as_garbage(zfs_object)
        else:
            raise e

    def collect_zfs_garbage(self, zfs_object):
        """Destroys ZFS parent objects

        Recursively destroys ZFS parent volumes and snapshots if they are
        marked as garbage

        :param zfs_object: full path to a volume or a snapshot
        """
        self._collect_garbage(zfs_object)

    def _collect_garbage(self, zfs_object):
        if zfs_object and zfs_object in self._needless_objects:
            sp = zfs_object.split('/')
            path = '/'.join(sp[:-1])
            name = sp[-1]
            if '@' in name:  # it's a snapshot:
                volume, snap = name.split('@')
                parent = '/'.join((path, volume))
                url = self.get_delete_snapshot_url(zfs_object)
                try:
                    self.nef.delete(url)
                except exception.NexentaException as exc:
                    LOG.debug('Error occurred while trying to delete '
                              'snapshot: {}'.format(exc))
                    return
            else:
                url = self.get_original_snapshot_url(zfs_object)
                # Check if there is a parent snapshot
                field = 'originalSnapshot'
                parent = self.nef.get('{}?fields={}'.format(
                    url, field)).get(field)

                url = self.get_delete_volume_url(zfs_object)
                try:
                    self.nef.delete(url)
                except exception.NexentaException as exc:
                    LOG.debug('Error occurred while trying to delete '
                              'volume: {}'.format(exc))
                    return
            self._needless_objects.remove(zfs_object)
            self._collect_garbage(parent)

    def get_delete_snapshot_url(self, zfs_object):
        raise NotImplementedError()

    def get_original_snapshot_url(self, zfs_object):
        raise NotImplementedError()

    def get_delete_volume_url(self, zfs_object):
        raise NotImplementedError()
