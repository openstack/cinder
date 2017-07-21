Replication
===========

For backend devices that offer replication features, Cinder provides a common
mechanism for exposing that functionality on a per volume basis while still
trying to allow flexibility for the varying implementation and requirements of
all the different backend devices.

There are 2 sides to Cinder's replication feature, the core mechanism and the
driver specific functionality, and in this document we'll only be covering the
driver side of things aimed at helping vendors implement this functionality in
their drivers in a way consistent with all other drivers.

Although we'll be focusing on the driver implementation there will also be some
mentions on deployment configurations to provide a clear picture to developers
and help them avoid implementing custom solutions to solve things that were
meant to be done via the cloud configuration.

Overview
--------

As a general rule replication is enabled and configured via the cinder.conf
file under the driver's section, and volume replication is requested through
the use of volume types.

*NOTE*: Current replication implementation is v2.1 and it's meant to solve a
very specific use case, the "smoking hole" scenario.  It's critical that you
read the Use Cases section of the spec here:
https://specs.openstack.org/openstack/cinder-specs/specs/mitaka/cheesecake.html

From a user's perspective volumes will be created using specific volume types,
even if it is the default volume type, and they will either be replicated or
not, which will be reflected on the ``replication_status`` field of the volume.
So in order to know if a snapshot is replicated we'll have to check its volume.

After the loss of the primary storage site all operations on the resources will
fail and VMs will no longer have access to the data.  It is then when the Cloud
Administrator will issue the ``failover-host`` command to make the
cinder-volume service perform the failover.

After the failover is completed, the Cinder volume service will start using the
failed-over secondary storage site for all operations and the user will once
again be able to perform actions on all resources that were replicated, while
all other resources will be in error status since they are no longer available.

Storage Device configuration
----------------------------

Most storage devices will require configuration changes to enable the
replication functionality, and this configuration process is vendor and storage
device specific so it is not contemplated by the Cinder core replication
functionality.

It is up to the vendors whether they want to handle this device configuration
in the Cinder driver or as a manual process, but the most common approach is to
avoid including this configuration logic into Cinder and having the Cloud
Administrators do a manual process following a specific guide to enable
replication on the storage device before configuring the cinder volume service.

Service configuration
---------------------

The way to enable and configure replication is common to all drivers and it is
done via the ``replication_device`` configuration option that goes in the
driver's specific section in the ``cinder.conf`` configuration file.

``replication_device`` is a multi dictionary option, that should be specified
for each replication target device the admin wants to configure.

While it is true that all drivers use the same ``replication_device``
configuration option this doesn't mean that they will all have the same data,
as there is only one standardized and **REQUIRED** key in the configuration
entry, all others are vendor specific:

- backend_id:<vendor-identifier-for-rep-target>

Values of ``backend_id`` keys are used to uniquely identify within the driver
each of the secondary sites, although they can be reused on different driver
sections.

These unique identifiers will be used by the failover mechanism as well as in
the driver initialization process, and the only requirement is that is must
never have the value "default".

An example driver configuration for a device with multiple replication targets
is show below::

    .....
    [driver-biz]
    volume_driver=xxxx
    volume_backend_name=biz

    [driver-baz]
    volume_driver=xxxx
    volume_backend_name=baz

    [driver-foo]
    volume_driver=xxxx
    volume_backend_name=foo
    replication_device = backend_id:vendor-id-1,unique_key:val....
    replication_device = backend_id:vendor-id-2,unique_key:val....

In this example the result of calling
``self.configuration.safe_get('replication_device)`` within the driver is the
following list::

    [{backend_id: vendor-id-1, unique_key: val1},
     {backend_id: vendor-id-2, unique_key: val2}]

It is expected that if a driver is configured with multiple replication
targets, that replicated volumes are actually replicated on **all targets**.

Besides specific replication device keys defined in the ``replication_device``,
a driver may also have additional normal configuration options in the driver
section related with the replication to allow Cloud Administrators to configure
things like timeouts.

Capabilities reporting
----------------------

There are 2 new replication stats/capability keys that drivers supporting
relication v2.1 should be reporting: ``replication_enabled`` and
``replication_targets``::

    stats["replication_enabled"] = True|False
    stats["replication_targets"] = [<backend-id_1, <backend-id_2>...]

If a driver is behaving correctly we can expect the ``replication_targets``
field to be populated whenever ``replication_enabled`` is set to ``True``, and
it is expected to either be set to ``[]`` or be missing altogether when
``replication_enabled`` is set to ``False``.

The purpose of the ``replication_enabled`` field is to be used by the scheduler
in volume types for creation and migrations.

As for the ``replication_targets`` field it is only provided for informational
purposes so it can be retrieved through the ``get_capabilities`` using the
admin REST API, but it will not be used for validation at the API layer.  That
way Cloud Administrators will be able to know available secondary sites where
they can failover.

Volume Types / Extra Specs
---------------------------

The way to control the creation of volumes on a cloud with backends that have
replication enabled is, like with many other features, through the use of
volume types.

We won't go into the details of volume type creation, but suffice to say that
you will most likely want to use volume types to discriminate between
replicated and non replicated volumes and be explicit about it so that non
replicated volumes won't end up in a replicated backend.

Since the driver is reporting the ``replication_enabled`` key, we just need to
require it for replication volume types adding ``replication_enabled='<is>
True``` and also specifying it for all non replicated volume types
``replication_enabled='<is> False'``.

It's up to the driver to parse the volume type info on create and set things up
as requested.  While the scoping key can be anything, it's strongly recommended
that all backends utilize the same key (replication) for consistency and to
make things easier for the Cloud Administrator.

Additional replication parameters can be supplied to the driver using vendor
specific properties through the volume type's extra-specs so they can be used
by the driver at volume creation time, or retype.

It is up to the driver to parse the volume type info on create and retype to
set things up as requested.  A good pattern to get a custom parameter from a
given volume instance is this::

    extra_specs = getattr(volume.volume_type, 'extra_specs', {})
    custom_param = extra_specs.get('custom_param', 'default_value')

It may seem convoluted, but we must be careful when retrieving the
``extra_specs`` from the ``volume_type`` field as it could be ``None``.

Vendors should try to avoid obfuscating their custom properties and expose them
using the ``_init_vendor_properties`` method so they can be checked by the
Cloud Administrator using the ``get_capabilities`` REST API.

*NOTE*: For storage devices doing per backend/pool replication the use of
volume types is also recommended.

Volume creation
---------------

Drivers are expected to honor the replication parameters set in the volume type
during creation, retyping, or migration.

When implementing the replication feature there are some driver methods that
will most likely need modifications -if they are implemented in the driver
(since some are optional)- to make sure that the backend is replicating volumes
that need to be replicated and not replicating those that don't need to be:

- ``create_volume``
- ``create_volume_from_snapshot``
- ``create_cloned_volume``
- ``retype``
- ``clone_image``
- ``migrate_volume``

In these methods the driver will have to check the volume type to see if the
volumes need to be replicated, we could use the same pattern described in the
`Volume Types / Extra Specs`_ section::

    def _is_replicated(self, volume):
        specs = getattr(volume.volume_type, 'extra_specs', {})
        return specs.get('replication_enabled') == '<is> True'

But it is **not** the recommended mechanism, and the ``is_replicated`` method
available in volumes and volume types versioned objects instances should be
used instead.

Drivers are expected to keep the ``replication_status`` field up to date and in
sync with reality, usually as specified in the volume type.  To do so in above
mentioned methods' implementation they should use the update model mechanism
provided for each one of those methods.  One must be careful since the update
mechanism may be different from one method to another.

What this means is that most of these methods should be returning a
``replication_status`` key with the value set to ``enabled`` in the model
update dictionary if the volume type is enabling replication.  There is no need
to return the key with the value of ``disabled`` if it is not enabled since
that is the default value.

In the case of the ``create_volume``, and ``retype`` method there is no need to
return the ``replication_status`` in the model update since it has already been
set by the scheduler on creation using the extra spec from the volume type. And
on ``migrate_volume`` there is no need either since there is no change to the
``replication_status``.

*NOTE*: For storage devices doing per backend/pool replication it is not
necessary to check the volume type for the ``replication_enabled`` key since
all created volumes will be replicated, but they are expected to return the
``replication_status`` in all those methods, including the ``create_volume``
method since the driver may receive a volume creation request without the
replication enabled extra spec and therefore the driver will not have set the
right ``replication_status`` and the driver needs to correct this.

Besides the ``replication_status`` field that drivers need to update there are
other fields in the database related to the replication mechanism that the
drivers can use:

- ``replication_extended_status``
- ``replication_driver_data``

These fields are string type fields with a maximum size of 255 characters and
they are available for drivers to use internally as they see fit for their
normal replication operation.  So they can be assigned in the model update and
later on used by the driver, for example during the failover.

To avoid using magic strings drivers must use values defined by the
``ReplicationsSatus`` class in ``cinder/objects/fields.py`` file and
these are:

- ``ERROR``: When setting the replication failed on creation, retype, or
  migrate.  This should be accompanied by the volume status ``error``.
- ``ENABLED``: When the volume is being replicated.
- ``DISABLED``: When the volume is not being replicated.
- ``FAILED_OVER``: After a volume has been successfully failed over.
- ``FAILOVER_ERROR``: When there was an error during the failover of this
  volume.
- ``NOT_CAPABLE``: When we failed-over but the volume was not replicated.

The first 3 statuses revolve around the volume creation and the last 3 around
the failover mechanism.

The only status that should not be used for the volume's ``replication_status``
is the ``FAILING_OVER`` status.

Whenever we are referring to values of the ``replication_status`` in this
document we will be referring to the ``ReplicationStatus`` attributes and not a
literal string, so ``ERROR`` means
``cinder.objects.field.ReplicationStatus.ERROR`` and not the string "ERROR".

Failover
--------

This is the mechanism used to instruct the cinder volume service to fail over
to a secondary/target device.

Keep in mind the use case is that the primary backend has died a horrible death
and is no longer valid, so any volumes that were on the primary and were not
being replicated will no longer be available.

The method definition required from the driver to implement the failback
mechanism is as follows::

    def failover_host(self, context, volumes, secondary_id=None):

There are several things that are expected of this method:

- Promotion of a secondary storage device to primary
- Generating the model updates
- Changing internally to access the secondary storage device for all future
  requests.

If no secondary storage device is provided to the driver via the ``backend_id``
argument (it is equal to ``None``), then it is up to the driver to choose which
storage device to failover to.  In this regard it is important that the driver
takes into consideration that it could be failing over from a secondary (there
was a prior failover request), so it should discard current target from the
selection.

If the ``secondary_id`` is not a valid one the driver is expected to raise
``InvalidReplicationTarget``, for any other non recoverable errors during a
failover the driver should raise ``UnableToFailOver`` or any child of
``VolumeDriverException`` class and revert to a state where the previous
backend is in use.

The failover method in the driver will receive a list of replicated volumes
that need to be failed over.  Replicated volumes passed to the driver may have
diverse ``replication_status`` values, but they will always be one of:
``ENABLED``, ``FAILED_OVER``, or ``FAILOVER_ERROR``.

The driver must return a 2-tuple with the new storage device target id as the
first element and a list of dictionaries with the model updates required for
the volumes so that the driver can perform future actions on those volumes now
that they need to be accessed on a different location.

It's not a requirement for the driver to return model updates for all the
volumes, or for any for that matter as it can return ``None`` or an empty list
if there's no update necessary.  But if elements are returned in the model
update list then it is a requirement that each of the dictionaries contains 2
key-value pairs, ``volume_id`` and ``updates`` like this::

    [{
         'volume_id': volumes[0].id,
         'updates': {
             'provider_id': new_provider_id1,
             ...
         },
         'volume_id': volumes[1].id,
         'updates': {
             'provider_id': new_provider_id2,
             'replication_status': fields.ReplicationStatus.FAILOVER_ERROR,
             ...
         },
    }]

In these updates there is no need to set the ``replication_status`` to
``FAILED_OVER`` if the failover was successful, as this will be performed by
the manager by default, but it won't create additional DB queries if it is
returned.  It is however necessary to set it to ``FAILOVER_ERROR`` for those
volumes that had errors during the failover.

Driver's don't have to worry about snapshots or non replicated volumes, since
the manager will take care of those in the following manner:

- All non replicated volumes will have their current ``status`` field saved in
  the ``previous_status`` field, the ``status`` field changed to ``error``, and
  their ``replication_status`` set to ``NOT_CAPABLE``.
- All snapshots from non replicated volumes will have their statuses changed to
  ``error``.
- All replicated volumes that failed on the failover will get their ``status``
  changed to ``error``, their current ``status`` preserved in
  ``previous_status``, and their ``replication_status`` set to
  ``FAILOVER_ERROR`` .
- All snapshots from volumes that had errors during the failover will have
  their statuses set to ``error``.

Any model update request from the driver that changes the ``status`` field will
trigger a change in the ``previous_status`` field to preserve the current
status.

Once the failover is completed the driver should be pointing to the secondary
and should be able to create and destroy volumes and snapshots as usual, and it
is left to the Cloud Administrator's discretion whether resource modifying
operations are allowed or not.

Failback
--------

Drivers are not required to support failback, but they are required to raise a
``InvalidReplicationTarget`` exception if the failback is requested but not
supported.

The way to request the failback is quite simple, the driver will receive the
argument ``secondary_id`` with the value of ``default``.  That is why if was
forbidden to use the ``default`` on the target configuration in the cinder
configuration file.

Expected driver behavior is the same as the one explained in the `Failover`_
section:

- Promotion of the original primary to primary
- Generating the model updates
- Changing internally to access the original primary storage device for all
  future requests.

If the failback of any of the volumes fail the driver must return
``replication_status`` set to ``ERROR`` in the volume updates for those
volumes.  If they succeed it is not necessary to change the
``replication_status`` since the default behavior will be to set them to
``ENABLED``, but it won't create additional DB queries if it is set.

The manager will update resources in a slightly different way than in the
failover case:

- All non replicated volumes will not have any model modifications.
- All snapshots from non replicated volumes will not have any model
  modifications.
- All replicated volumes that failed on the failback will get their ``status``
  changed to ``error``, have their current ``status`` preserved in the
  ``previous_status`` field, and their ``replication_status`` set to
  ``FAILOVER_ERROR``.
- All snapshots from volumes that had errors during the failover will have
  their statuses set to ``error``.

We can avoid using the "default" magic string by using the
``FAILBACK_SENTINEL`` class attribute from the ``VolumeManager`` class.

Initialization
--------------

It stands to reason that a failed over Cinder volume service may be restarted,
so there needs to be a way for a driver to know on start which storage device
should be used to access the resources.

So, to let drivers know which storage device they should use the manager passes
drivers the ``active_backend_id`` argument to their ``__init__`` method during
the initialization phase of the driver.  Default value is ``None`` when the
default (primary) storage device should be used.

Drivers should store this value if they will need it, as the base driver is not
storing it, for example to determine the current storage device when a failover
is requested and we are already in a failover state, as mentioned above.

Freeze / Thaw
-------------

In many cases, after a failover has been completed we'll want to allow changes
to the data in the volumes as well as some operations like attach and detach
while other operations that modify the number of existing resources, like
delete or create, are not allowed.

And that is where the freezing mechanism comes in; freezing a backend puts the
control plane of the specific Cinder volume service into a read only state, or
at least most of it, while allowing the data plane to proceed as usual.

While this will mostly be handled by the Cinder core code, drivers are informed
when the freezing mechanism is enabled or disabled via these 2 calls::

    freeze_backend(self, context)
    thaw_backend(self, context)

In most cases the driver may not need to do anything, and then it doesn't need
to define any of these methods as long as its a child class of the ``BaseVD``
class that already implements them as noops.

Raising a `VolumeDriverException` exception in any of these methods will result
in a 500 status code response being returned to the caller and the manager will
not log the exception, so it's up to the driver to log the error if it is
appropriate.

If the driver wants to give a more meaningful error response, then it can raise
other exceptions that have different status codes.

When creating the `freeze_backend` and `thaw_backend` driver methods we must
remember that this is a Cloud Administrator operation, so we can return errors
that reveal internals of the cloud, for example the type of storage device, and
we must use the appropriate internationalization translation methods when
raising exceptions; for `VolumeDriverException` no translation is necessary
since the manager doesn't log it or return to the user in any way, but any
other exception should use the ``_()`` translation method since it will be
returned to the REST API caller.

For example, if a storage device doesn't support the thaw operation when failed
over, then it should raise an `Invalid` exception::

    def thaw_backend(self, context):
        if self.failed_over:
            msg = _('Thaw is not supported by driver XYZ.')
            raise exception.Invalid(msg)
