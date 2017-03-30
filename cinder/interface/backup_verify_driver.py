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
Backup driver with verification interface.

Used for backup drivers that support the option to verify the backup after
completion.
"""

from cinder.interface import backup_driver


class BackupDriverWithVerify(backup_driver.BackupDriver):
    """Backup driver that supports the optional verification."""

    def verify(self, backup):
        """Verify that the backup exists on the backend.

        Verify that the backup is OK, possibly following an import record
        operation.

        :param backup: Backup id of the backup to verify.
        :raises InvalidBackup, NotImplementedError:
        """
