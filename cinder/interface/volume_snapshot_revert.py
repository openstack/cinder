# Copyright 2018 Huawei
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
Revert to snapshot capable volume driver interface.
"""

from cinder.interface import base


class VolumeSnapshotRevertDriver(base.CinderInterface):
    """Interface for drivers that support revert to snapshot."""

    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert volume to snapshot.

        Note: the revert process should not change the volume's
        current size, that means if the driver shrank
        the volume during the process, it should extend the
        volume internally.

        :param context: the context of the caller.
        :param volume: The volume to be reverted.
        :param snapshot: The snapshot used for reverting.
        """
