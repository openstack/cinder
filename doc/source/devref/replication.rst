Replication
============

How to implement replication features in a backend driver.

For backend devices that offer replication features, Cinder
provides a common mechanism for exposing that functionality
on a volume per volume basis while still trying to allow
flexibility for the varying implementation and requirements
of all the different backend devices.

Most of the configuration is done via the cinder.conf file
under the driver section and through the use of volume types.

NOTE:
This implementation is intended to solve a specific use case.
It's critical that you read the Use Cases section of the spec
here:
https://specs.openstack.org/openstack/cinder-specs/specs/mitaka/cheesecake.html

Config file examples
--------------------

The cinder.conf file is used to specify replication config info
for a specific driver. There is no concept of managed vs unmanaged,
ALL replication configurations are expected to work by using the same
driver.  In other words, rather than trying to perform any magic
by changing host entries in the DB for a Volume etc, all replication
targets are considered "unmanged" BUT if a failover is issued, it's
the drivers responsibility to access replication volumes on the replicated
backend device.

This results in no changes for the end-user.  For example, He/She can
still issue an attach call to a replicated volume that has been failed
over, and the driver will still receive the call BUT the driver will
need to figure out if it needs to redirect the call to the a different
backend than the default or not.

Information regarding if the backend is in a failed over state should
be stored in the driver, and in the case of a restart, the service
entry in the DB will have the replication status info and pass it
in during init to allow the driver to be set in the correct state.

In the case of a failover event, and a volume was NOT of type
replicated, that volume will now be UNAVAILABLE and any calls
to access that volume should return a VolumeNotFound exception.

**replication_device**

Is a multi-dict opt, that should be specified
for each replication target device the admin would
like to configure.

*NOTE:*

There is one standardized and REQUIRED key in the config
entry, all others are vendor-unique:

* backend_id:<vendor-identifier-for-rep-target>

An example driver config for a device with multiple replication targets
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

In this example the result is self.configuration.get('replication_device) with the list::

    [{backend_id: vendor-id-1, unique_key: val1},
     {backend_id: vendor-id-2, unique_key: val1}]



Volume Types / Extra Specs
---------------------------
In order for a user to specify they'd like a replicated volume, there needs to be
a corresponding Volume Type created by the Cloud Administrator.

There's a good deal of flexibility by using volume types.  The scheduler can
send the create request to a backend that provides replication by simply
providing the replication=enabled key to the extra-specs of the volume type.

For example, if the type was set to simply create the volume on any (or if you only had one)
backend that supports replication, the extra-specs entry would be::

    {replication: enabled}

Additionally you could provide additional details using scoped keys::
    {replication: enabled, volume_backend_name: foo,
     replication: replication_type: async}

It's up to the driver to parse the volume type info on create and set things up
as requested.  While the scoping key can be anything, it's strongly recommended that all
backends utilize the same key (replication) for consistency and to make things easier for
the Cloud Administrator.

Additionally it's expected that if a backend is configured with 3 replication
targets, that if a volume of type replication=enabled is issued against that
backend then it will replicate to ALL THREE of the configured targets.

Capabilities reporting
----------------------
The following entries are expected to be added to the stats/capabilities update for
replication configured devices::

    stats["replication_enabled"] = True|False
    stats["replication_targets"] = [<backend-id_1, <backend-id_2>...]

NOTICE, we report configured replication targets via volume stats_update
This information is added to the get_capabilities admin call.

Required methods
-----------------
The number of API methods associated with replication is intentionally very limited,

Admin only methods.

They include::
    replication_failover(self, context, volumes)

Additionally we have freeze/thaw methods that will act on the scheduler
but may or may not require something from the driver::

    freeze_backend(self, context)
    thaw_backend(self, context)

**replication_failover**

Used to instruct the backend to fail over to the secondary/target device.
If not secondary is specified (via backend_id argument) it's up to the driver
to choose which device to failover to.  In the case of only a single
replication target this argument should be ignored.

Note that ideally drivers will know how to update the volume reference properly so that Cinder is now
pointing to the secondary.  Also, while it's not required, at this time; ideally the command would
act as a toggle, allowing to switch back and forth between primary and secondary and back to primary.

Keep in mind the use case is that the backend has died a horrible death and is
no longer valid.  Any volumes that were on the primary and NOT of replication
type should now be unavailable.

NOTE:  We do not expect things like create requests to go to the driver and
magically create volumes on the replication target.  The concept is that the
backend is lost, and we're just providing a DR mechanism to preserve user data
for volumes that were specified as such via type settings.

**freeze_backend**
Puts a backend host/service into a R/O state for the control plane.  For
example if a failover is issued, it is likely desirable that while data access
to existing volumes is maintained, it likely would not be wise to continue
doing things like creates, deletes, extends etc.

**thaw_backend**
Clear frozen control plane on a backend.
