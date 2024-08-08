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

All backend drivers should support this interface as a bare minimum, but some
methods (marked as optional in their description) can rely on the default
implementation.
"""

from cinder.interface import base


class VolumeDriverCore(base.CinderInterface):
    """Core backend driver required interface."""

    def do_setup(self, context):
        """Any initialization the volume driver needs to do while starting.

        Called once by the manager after the driver is loaded.
        Can be used to set up clients, check licenses, set up protocol
        specific helpers, etc.

        If you choose to raise an exception here, the setup is considered
        failed already and the check_for_setup_error() will not be called.

        :param context: The admin context of type context.RequestContext.
        :raises InvalidConfigurationValue: raise this if you detect a problem
                                           during a configuration check
        :raises VolumeDriverException: raise this or one of its more specific
                                       subclasses if you detect setup problems
                                       other than invalid configuration
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
        :raises InvalidConfigurationValue: raise this if you detect a problem
                                           during a configuration check
        """

    def get_volume_stats(self, refresh=False):
        """Collects volume backend stats.

        The get_volume_stats method is used by the volume manager to collect
        information from the driver instance related to information about the
        driver, available and used space, and driver/backend capabilities.

        stats are stored in 'self._stats' field, which could be updated in
        '_update_volume_stats' method.

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
            string such as: "iSCSI", "FC", "NFS", "ceph", etc.
            Available protocols are present in cinder.common.constants and they
            must be used instead of string literals.
            Variant values only exist for older drivers that were already
            reporting those values.  New drivers must use non variant versions.
            In some cases this may be the same value as the driver_volume_type
            returned by the initialize_connection method, but they are not the
            same thing, since this one is meant to be used by the scheduler,
            while the latter is the os-brick connector identifier used in the
            factory method.

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
        * clone_across_pools (Boolean)
            Whether the backend supports cloning a volume across different
            pools. Defaults to False.

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

        It is imperative that this operation ensures that the data from the
        deleted volume cannot leak into new volumes when they are created, as
        new volumes are likely to belong to a different tenant/project.

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

    def terminate_connection(self, volume, connector):
        """Remove access to a volume.

        Note: If ``connector`` is ``None``, then all connections to the volume
        should be terminated.

        :param volume: The volume to remove.
        :param connector: The Dictionary containing information about the
                          connection. This is optional when doing a
                          force-detach and can be None.
        """

    def clone_image(self, context, volume,
                    image_location, image_meta, image_service):
        """Create a volume efficiently from an existing image.

        Drivers that, always or under some circumstances, can efficiently
        create a volume from a Glance image can implement this method to be
        given a chance to try to do the volume creation as efficiently as
        possible.

        If the driver cannot do it efficiently on a specific call it can
        return ``(None, False)`` to let Cinder try other mechanisms.

        **This method is optional** and most drivers won't need to implement
        it and can leverage the default driver implementation that returns
        ``(None, False)`` to indicate that this optimization is not possible on
        this driver.

        Examples where drivers can do this optimization:

        - When images are stored on the same storage system and the driver can
          locate them and efficiently create a volume.  For example the RBD
          driver can efficiently create a volume if the image is stored on the
          same Ceph cluster and the image format is ``raw``.  Another example
          is the GPFS driver.

        - When volumes are locally accessible and accessing them that way is
          more efficient than going through the remote connection mechanism.
          For example in the GPFS driver if the cloning feature doesn't work it
          will copy the file without using os-brick to connect to the volume.

        :param context: Security/policy info for the request.
        :param volume: The volume to create, as an OVO instance. Drivers should
                       use attributes to access its values instead of using the
                       dictionary compatibility interface it provides.
        :param image_location: Tuple with (``direct_url``, ``locations``) from
                               the `image metadata fields.
                               <https://docs.openstack.org/api-ref/image/v2/index.html?expanded=show-image-detail#show-image-detail>`_
                               ``direct_url``, when present, is a string whose
                               format depends on the image service's external
                               storage in use.
                               Any, or both, tuple positions can be None,
                               depending on the image service configuration.
                               ``locations``, when present, is a list of
                               dictionaries where the value of the ``url`` key
                               contains the direct urls (including the one from
                               ``direct_url``).
        :param image_meta: Dictionary containing `information about the image
                           <https://docs.openstack.org/api-ref/image/v2/index.html?expanded=show-image-detail#show-image-detail>`_,
                           including basic attributes and custom properties.
                           Some transformations have been applied, such as
                           converting timestamps (from ``created_at``,
                           ``updated_at``, and ``deleted_at``) to datetimes,
                           and deserializing JSON values from
                           ``block_device_mapping`` and ``mappings`` keys if
                           present.
                           Base properties, as per the image's schema, will be
                           stored on the base dictionary and the rest will be
                           stored under the ``properties`` key.
                           An important field to check in this method is the
                           ``disk_format`` (e.g.  raw, qcow2).
        :param image_service: The image service to use (``GlanceImageService``
                              instance).  Can fetch image data directly using
                              it.
        :returns: Tuple of (model_update, boolean) where the boolean specifies
                  whether the clone occurred.
        """

    def copy_image_to_volume(self, context, volume, image_service, image_id,
                             disable_sparse=False):
        """Fetch the image from image_service and write it to the volume.

        :param context: Security/policy info for the request.
        :param volume: The volume to create.
        :param image_service: The image service to use.
        :param image_id: The image identifier.
        :param disable_sparse: Enable or disable sparse copy. Default=False.
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

    def before_volume_copy(self, context, src_vol, dest_vol, remote=None):
        """Driver-specific actions executed before copying a volume.

        This method will be called before _copy_volume_data during volume
        migration.

        :param context: Context
        :param src_volume: Source volume in the copy operation.
        :param dest_volume: Destination volume in the copy operation.
        :param remote: Whether the copy operation is local.
        :returns: There is no return value for this method.
        """

    def after_volume_copy(self, context, src_vol, dest_vol, remote=None):
        """Driver-specific actions executed after copying a volume.

        This method will be called after _copy_volume_data during volume
        migration.

        :param context: Context
        :param src_volume: Source volume in the copy operation.
        :param dest_volume: Destination volume in the copy operation.
        :param remote: Whether the copy operation is local.
        :returns: There is no return value for this method.
        """

    def extend_volume(self, volume, new_size):
        """Extend the size of a volume.

        :param volume: The volume to extend.
        :param new_size: The new desired size of the volume.

        Note that if the volume backend doesn't support extending an in-use
        volume, the driver should report online_extend_support=False.
        """

    def migrate_volume(self, context, volume, host):
        """Migrate the volume to the specified host.

        :param context: Context
        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        :returns: Tuple of (model_update, boolean) where the boolean specifies
                  whether the migration occurred.
        """

    def update_migrated_volume(self, context, volume, new_volume,
                               original_volume_status):
        """Return model update for migrated volume.

        Each driver implementing this method needs to be responsible for the
        values of _name_id and provider_location. If None is returned or either
        key is not set, it means the volume table does not need to change the
        value(s) for the key(s).
        The return format is {"_name_id": value, "provider_location": value}.

        :param context: Context
        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :param original_volume_status: The status of the original volume
        :returns: model_update to update DB with any needed changes
        """

    def retype(self, context, volume, new_type, diff, host):
        """Change the type of a volume.

        This operation occurs on the same backend and the return value
        indicates whether it was successful.  If migration is required
        to satisfy a retype, that will be handled by the volume manager.

        :param context: Context
        :param volume: The volume to retype
        :param new_type: The target type for the volume
        :param diff: The differences between the two types
        :param host: The host that contains this volume
        :returns: Tuple of (boolean, model_update) where the boolean specifies
                  whether the retype occurred.
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

    def set_initialized(self):
        """Mark driver as initialized.

        Do not implement this in a driver. Rely on the default implementation.
        """

    def initialized(self):
        """Getter for driver's initialized status.

        Do not implement this in a driver. Rely on the default implementation.
        """

    def supported(self):
        """Getter for driver's supported status.

        Do not implement this in a driver. Rely on the default implementation.
        """

    def set_throttle(self):
        """Hook for initialization of cinder.volume.throttle.

        This has not been necessary to re-implement or override in any
        drivers thus far. The generic implementation does nothing unless
        explicitly enabled.
        """

    def init_capabilities(self):
        """Fetch and merge capabilities of the driver.

        Do not override this, implement _init_vendor_properties instead.
        """

    def _init_vendor_properties(self):
        """Create a dictionary of vendor unique properties.

        Compose a dictionary by calling ``self._set_property``.

        Select a prefix from the vendor, product, or device name.
        Prefix must match the part of property name before colon (:).

        :returns tuple (properties: dict, prefix: str)
        """

    def update_provider_info(self, volumes, snapshots):
        """Get provider info updates from driver.

        This retrieves a list of volumes and a list of snapshots that
        changed their providers thanks to the initialization of the host,
        so that Cinder can update this information in the volume database.

        This is only implemented by drivers where such migration is possible.

        :param volumes: List of Cinder volumes to check for updates
        :param snapshots: List of Cinder snapshots to check for updates
        :returns: tuple (volume_updates, snapshot_updates)

        where volume updates {'id': uuid, provider_id: <provider-id>}
        and snapshot updates {'id': uuid, provider_id: <provider-id>}
        """
