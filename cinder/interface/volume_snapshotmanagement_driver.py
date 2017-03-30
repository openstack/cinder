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
Manage/unmanage existing volume snapshots driver interface.
"""

from cinder.interface import base


class VolumeSnapshotManagementDriver(base.CinderInterface):
    """Interface for drivers that support managing existing snapshots."""

    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        existing_ref is passed straight through from the API request's
        manage_existing_ref value, and it is up to the driver how this should
        be interpreted.  It should be sufficient to identify a storage object
        that the driver should somehow associate with the newly-created cinder
        snapshot structure.

        There are two ways to do this:

        1. Rename the backend storage object so that it matches the
           snapshot['name'] which is how drivers traditionally map between a
           cinder snapshot and the associated backend storage object.

        2. Place some metadata on the snapshot, or somewhere in the backend,
           that allows other driver requests (e.g. delete) to locate the
           backend storage object when required.

        :param snapshot: The snapshot to manage.
        :param existing_ref: Dictionary with keys 'source-id', 'source-name'
                             with driver-specific values to identify a backend
                             storage object.
        :raises ManageExistingInvalidReference: If the existing_ref doesn't
                 make sense, or doesn't refer to an existing backend storage
                 object.
        """

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return size of snapshot to be managed by manage_existing.

        When calculating the size, round up to the next GB.

        :param snapshot: The snapshot to manage.
        :param existing_ref: Dictionary with keys 'source-id', 'source-name'
                             with driver-specific values to identify a backend
                             storage object.
        :raises ManageExistingInvalidReference: If the existing_ref doesn't
                 make sense, or doesn't refer to an existing backend storage
                 object.
        """

    def unmanage_snapshot(self, snapshot):
        """Removes the specified snapshot from Cinder management.

        Does not delete the underlying backend storage object.

        For most drivers, this will not need to do anything. However, some
        drivers might use this call as an opportunity to clean up any
        Cinder-specific configuration that they have associated with the
        backend storage object.

        :param snapshot: The snapshot to unmanage.
        """
