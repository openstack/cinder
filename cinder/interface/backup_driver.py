# Copyright 2016 Dell Inc.
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
#

"""
Core backup driver interface.

All backup drivers should support this interface as a bare minimum.
"""

from cinder.interface import base


class BackupDriver(base.CinderInterface):
    """Backup driver required interface."""

    def get_metadata(self, volume_id):
        """Get volume metadata.

        Returns a json-encoded dict containing all metadata and the restore
        version i.e. the version used to decide what actually gets restored
        from this container when doing a backup restore.

        Typically best to use py:class:`BackupMetadataAPI` for this.

        :param volume_id: The ID of the volume.
        :returns: json-encoded dict of metadata.
        """

    def put_metadata(self, volume_id, json_metadata):
        """Set volume metadata.

        Typically best to use py:class:`BackupMetadataAPI` for this.

        :param volume_id: The ID of the volume.
        :param json_metadata: The json-encoded dict of metadata.
        """

    def backup(self, backup, volume_file, backup_metadata=False):
        """Start a backup of a specified volume.

        If backup['parent_id'] is given, then an incremental backup
        should be performed.

        If the parent backup is of different size, a full backup should be
        performed to ensure all data is included.

        :param backup: The backup information.
        :param volume_file: The volume or file to write the backup to.
        :param backup_metadata: Whether to include volume metadata in the
                                backup.

        The variable structure of backup in the following format::

           {
              'id': id,
              'availability_zone': availability_zone,
              'service': driver_name,
              'user_id': context.user_id,
              'project_id': context.project_id,
              'display_name': name,
              'display_description': description,
              'volume_id': volume_id,
              'status': fields.BackupStatus.CREATING,
              'container': container,
              'parent_id': parent_id,
              'size': size,
              'host': host,
              'snapshot_id': snapshot_id,
              'data_timestamp': data_timestamp,
           }

        service: backup driver
        parent_id: parent backup id
        size: equal to volume size
        data_timestamp: backup creation time
        """

    def restore(self, backup, volume_id, volume_file):
        """Restore volume from a backup.

        :param backup: The backup information.
        :param volume_id: The volume to be restored.
        :param volume_file: The volume or file to read the data from.
        """

    def delete_backup(self, backup):
        """Delete a backup from the backup store.

        :param backup: The backup to be deleted.
        """

    def export_record(self, backup):
        """Export driver specific backup record information.

        If backup backend needs additional driver specific information to
        import backup record back into the system it must override this method
        and return it as a dictionary so it can be serialized into a string.

        Default backup driver implementation has no extra information.

        :param backup: backup object to export
        :returns: driver_info - dictionary with extra information
        """

    def import_record(self, backup, driver_info):
        """Import driver specific backup record information.

        If backup backend needs additional driver specific information to
        import backup record back into the system it must override this method
        since it will be called with the extra information that was provided by
        export_record when exporting the backup.

        Default backup driver implementation does nothing since it didn't
        export any specific data in export_record.

        :param backup: backup object to export
        :param driver_info: dictionary with driver specific backup record
                            information
        :returns: None
        """

    def check_for_setup_error(self):
        """Method for checking if backup backend is successfully installed.

        Depends on storage backend limitations and driver implementation this
        method could check if all needed config options are configurated well
        or try to connect to the storage to verify driver can do it without
        any issues.

        :returns: None
        """
