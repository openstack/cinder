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
Backup driver with 'chunked' backup operations.
"""

from cinder.interface import backup_driver


class BackupChunkedDriver(backup_driver.BackupDriver):
    """Backup driver that supports 'chunked' backups."""

    def put_container(self, container):
        """Create the container if needed. No failure if it pre-exists.

        :param container: The container to write into.
        """

    def get_container_entries(self, container, prefix):
        """Get container entry names.

        :param container: The container from which to get entries.
        :param prefix: The prefix used to match entries.
        """

    def get_object_writer(self, container, object_name, extra_metadata=None):
        """Returns a writer which stores the chunk data in backup repository.

       :param container: The container to write to.
       :param object_name: The object name to write.
       :param extra_metadata: Extra metadata to be included.
       :returns: A context handler that can be used in a "with" context.
        """

    def get_object_reader(self, container, object_name, extra_metadata=None):
        """Returns a reader object for the backed up chunk.

       :param container: The container to read from.
       :param object_name: The object name to read.
       :param extra_metadata: Extra metadata to be included.
       """

    def delete_object(self, container, object_name):
        """Delete object from container.

       :param container: The container to modify.
       :param object_name: The object name to delete.
       """

    def update_container_name(self, backup, container):
        """Allows sub-classes to override container name.

        This method exists so that sub-classes can override the container name
        as it comes in to the driver in the backup object. Implementations
        should return None if no change to the container name is desired.
        """

    def get_extra_metadata(self, backup, volume):
        """Return extra metadata to use in prepare_backup.

        This method allows for collection of extra metadata in prepare_backup()
        which will be passed to get_object_reader() and get_object_writer().
        Subclass extensions can use this extra information to optimize
        data transfers.

         :returns: json serializable object
        """
