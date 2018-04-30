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
Core backend volume driver interface.

All backend drivers should support this interface as a bare minimum.
"""

from cinder.interface import base


class VolumeDriverCore(base.CinderInterface):
    """Core backend driver required interface."""

    def do_setup(self, context):
        """Any initialization the volume driver needs to do while starting.

        Called once by the manager after the driver is loaded.
        Can be used to set up clients, check licenses, set up protocol
        specific helpers, etc.

        :param context: The admin context.
        """

    def check_for_setup_error(self):
        """Validate there are no issues with the driver configuration.

        Called after do_setup(). Driver initialization can occur there or in
        this call, but must be complete by the time this returns.

        If this method raises an exception, the driver will be left in an
        "uninitialized" state by the volume manager, which means that it will
        not be sent requests for volume operations.

        This method typically checks things like whether the configured
        credentials can be used to log in the storage backend, and whether any
        external dependencies are present and working.

        :raises VolumeBackendAPIException: in case of setup error.
        """

    def get_volume_stats(self, refresh=False):
        """Collects volume backend stats.

        The get_volume_stats method is used by the volume manager to collect
        information from the driver instance related to information about the
        driver, available and used space, and driver/backend capabilities.

        It returns a dict with the following required fields:

        * volume_backend_name
            This is an identifier for the backend taken from cinder.conf.
            Useful when using multi-backend.
        * vendor_name
            Vendor/author of the driver who serves as the contact for the
            driver's development and support.
        * driver_version
            The driver version is logged at cinder-volume startup and is useful
            for tying volume service logs to a specific release of the code.
            There are currently no rules for how or when this is updated, but
            it tends to follow typical major.minor.revision ideas.
        * storage_protocol
            The protocol used to connect to the storage, this should be a short
            string such as: "iSCSI", "FC", "nfs", "ceph", etc.
        * total_capacity_gb
            The total capacity in gigabytes (GiB) of the storage backend being
            used to store Cinder volumes. Use keyword 'unknown' if the backend
            cannot report the value or 'infinite' if there is no upper limit.
            But, it is recommended to report real values as the Cinder
            scheduler assigns lowest weight to any storage backend reporting
            'unknown' or 'infinite'.

        * free_capacity_gb
            The free capacity in gigabytes (GiB). Use keyword 'unknown' if the
            backend cannot report the value or 'infinite' if there is no upper
            limit. But, it is recommended to report real values as the Cinder
            scheduler assigns lowest weight to any storage backend reporting
            'unknown' or 'infinite'.

        And the following optional fields:

        * reserved_percentage (integer)
            Percentage of backend capacity which is not used by the scheduler.
        * location_info (string)
            Driver-specific information used by the driver and storage backend
            to correlate Cinder volumes and backend LUNs/files.
        * QoS_support (Boolean)
            Whether the backend supports quality of service.
        * provisioned_capacity_gb
            The total provisioned capacity on the storage backend, in gigabytes
            (GiB), including space consumed by any user other than Cinder
            itself.
        * max_over_subscription_ratio
            The maximum amount a backend can be over subscribed.
        * thin_provisioning_support (Boolean)
            Whether the backend is capable of allocating thinly provisioned
            volumes.
        * thick_provisioning_support (Boolean)
            Whether the backend is capable of allocating thick provisioned
            volumes. (Typically True.)
        * total_volumes (integer)
            Total number of volumes on the storage backend. This can be used in
            custom driver filter functions.
        * filter_function (string)
            A custom function used by the scheduler to determine whether a
            volume should be allocated to this backend or not. Example:

              capabilities.total_volumes < 10

        * goodness_function (string)
            Similar to filter_function, but used to weigh multiple volume
            backends. Example:

              capabilities.capacity_utilization < 0.6 ? 100 : 25

        * multiattach (Boolean)
            Whether the backend supports multiattach or not. Defaults to False.
        * sparse_copy_volume (Boolean)
            Whether copies performed by the volume manager for operations such
            as migration should attempt to preserve sparseness.
        * online_extend_support (Boolean)
            Whether the backend supports in-use volume extend or not. Defaults
            to True.

        The returned dict may also contain a list, "pools", which has a similar
        dict for each pool being used with the backend.

        :param refresh: Whether to discard any cached values and force a full
                        refresh of stats.
        :returns: dict of appropriate values (see above).
        """

    def create_volume(self, volume):
        """Create a new volume on the backend.

        This method is responsible only for storage allocation on the backend.
        It should not export a LUN or actually make this storage available for
        use, this is done in a later call.

        TODO(smcginnis): Add example data structure of volume object.

        :param volume: Volume object containing specifics to create.
        :returns: (Optional) dict of database updates for the new volume.
        :raises VolumeBackendAPIException: if creation failed.
        """

    def delete_volume(self, volume):
        """Delete a volume from the backend.

        If the driver can talk to the backend and detects that the volume is no
        longer present, this call should succeed and allow Cinder to complete
        the process of deleting the volume.

        :param volume: The volume to delete.
        :raises VolumeIsBusy: if the volume is still attached or has snapshots.
                 VolumeBackendAPIException on error.
        """

    def initialize_connection(self, volume, connector, initiator_data=None):
        """Allow connection to connector and return connection info.

        :param volume: The volume to be attached.
        :param connector: Dictionary containing information about what is being
                          connected to.
        :param initiator_data: (Optional) A dictionary of driver_initiator_data
                               objects with key-value pairs that have been
                               saved for this initiator by a driver in previous
                               initialize_connection calls.
        :returns: A dictionary of connection information. This can optionally
                  include a "initiator_updates" field.

        The "initiator_updates" field must be a dictionary containing a
        "set_values" and/or "remove_values" field. The "set_values" field must
        be a dictionary of key-value pairs to be set/updated in the db. The
        "remove_values" field must be a list of keys, previously set with
        "set_values", that will be deleted from the db.

        May be called multiple times to get connection information after a
        volume has already been attached.
        """

    def attach_volume(self, context, volume, instance_uuid, host_name,
                      mountpoint):
        """Lets the driver know Nova has attached the volume to an instance.

        :param context: Security/policy info for the request.
        :param volume: Volume being attached.
        :param instance_uuid: ID of the instance being attached to.
        :param host_name: The host name.
        :param mountpoint: Device mount point on the instance.
        """

    def terminate_connection(self, volume, connector):
        """Remove access to a volume.

        :param volume: The volume to remove.
        :param connector: The Dictionary containing information about the
                          connection. This is optional when doing a
                          force-detach and can be None.
        """

    def detach_volume(self, context, volume, attachment=None):
        """Detach volume from an instance.

        :param context: Security/policy info for the request.
        :param volume: Volume being detached.
        :param attachment: (Optional) Attachment information.
        """

    def clone_image(self, volume, image_location, image_id, image_metadata,
                    image_service):
        """Clone an image to a volume.

        :param volume: The volume to create.
        :param image_location: Where to pull the image from.
        :param image_id: The image identifier.
        :param image_metadata: Information about the image.
        :param image_service: The image service to use.
        :returns: Model updates.
        """

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume.

        :param context: Security/policy info for the request.
        :param volume: The volume to create.
        :param image_service: The image service to use.
        :param image_id: The image identifier.
        :returns: Model updates.
        """

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image.

        :param context: Security/policy info for the request.
        :param volume: The volume to copy.
        :param image_service: The image service to use.
        :param image_meta: Information about the image.
        :returns: Model updates.
        """

    def extend_volume(self, volume, new_size):
        """Extend the size of a volume.

        :param volume: The volume to extend.
        :param new_size: The new desired size of the volume.

        Note that if the volume backend doesn't support extending an in-use
        volume, the driver should report online_extend_support=False.
        """

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: Information for the snapshot to be created.
        """

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: The snapshot to delete.
        """

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        If volume_type extra specs includes 'replication: <is> True'
        the driver needs to create a volume replica (secondary),
        and setup replication between the newly created volume and
        the secondary volume.

        An optional larger size for the new volume can be specified. Drivers
        should check this value and create or expand the new volume to match.

        :param volume: The volume to be created.
        :param snapshot: The snapshot from which to create the volume.
        :returns: A dict of database updates for the new volume.
        """
