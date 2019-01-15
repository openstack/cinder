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

from cinder import db
from cinder import objects


class VolumeMigration(object):
    """Lightweight Volume Migration object.

    Will be used by KeyMigrator instead of regular Volume object to avoid
    extra memory usage.
    """

    @staticmethod
    def from_volume(volume, context):
        volume_migration = VolumeMigration(volume.id,
                                           volume.user_id,
                                           volume.encryption_key_id)
        volume_migration._context = context
        return volume_migration

    def __init__(self, id, user_id, encryption_key_id):
        self.id = id
        self.user_id = user_id
        self.orig_encryption_key_id = encryption_key_id
        self.encryption_key_id = encryption_key_id

    def _get_updates(self):
        updates = {}
        if self.orig_encryption_key_id != self.encryption_key_id:
            updates['encryption_key_id'] = self.encryption_key_id
        return updates

    def _reset_changes(self):
        self.orig_encryption_key_id = self.encryption_key_id

    def save(self):
        updates = self._get_updates()
        if updates:
            db.volume_update(self._context, self.id, updates)
            self._reset_changes()

    def __str__(self):
        return 'id = {}'.format(self.id)

    def __repr__(self):
        return self.__str__()


class VolumeMigrationList(list):

    def __init__(self):
        list.__init__(self)

    def append(self, volumes, context):

        if not isinstance(volumes, objects.volume.VolumeList):
            return

        for volume in volumes:
            volume_migration = VolumeMigration.from_volume(volume, context)
            super(VolumeMigrationList, self).append(volume_migration)
