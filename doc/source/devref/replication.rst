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

Config file examples
--------------------

The cinder.conf file is used to specify replication target
devices for a specific driver.  Replication targets may
be specified as external (unmanaged) or internally
Cinder managed backend devices.

**replication_device**

Is a multi-dict opt, that should be specified
for each replication target device the admin would
like to configure.

*NOTE:*

There are two standardized keys in the config
entry, all others are vendor-unique:

* device_target_id:<vendor-identifier-for-rep-target>
* managed_backend_name:<cinder-backend-host-entry>,"


An example config entry for a managed replication device
would look like this::

    .....
    [driver-biz]
    volume_driver=xxxx
    volume_backend_name=biz

    [driver-foo]
    volume_driver=xxxx
    volume_backend_name=foo
    replication_device = device_target_id:vendor-id-info,managed_backend_name:biz,unique_key:val....

The use of multiopt will result in self.configuration.get('replication_device')
returning a list of properly formed python dictionaries that can
be easily consumed::

    [{device_target_id: blahblah, managed_backend_name: biz, unique_key: val1}]


In the case of multiple replication target devices::

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
    managed_replication_target=True
    replication_device = device_target_id:vendor-id-info,managed_backend_name:biz,unique_key:val....
    replication_device = device_target_id:vendor-id-info,managed_backend_name:baz,unique_key:val....

In this example the result is self.configuration.get('replication_device')
returning a list of properly formed python dictionaries::

    [{device_target_id: blahblah, managed_backend_name: biz, unique_key: val1},
     {device_target_id: moreblah, managed_backend_name: baz, unique_key: val1}]


In the case of unmanaged replication target devices::

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
    replication_device = device_target_id:vendor-id-info,managed_backend_name:None,unique_key:val....
    replication_device = device_target_id:vendor-id-info,managed_backend_name:None,unique_key:val....

The managed_backend_name entry may also be omitted altogether in the case of unmanaged targets.

In this example the result is self.configuration.get('replication_device) with the list::

    [{device_target_id: blahblah, managed_backend_name: None, unique_key: val1},
     {device_target_id: moreblah, managed_backend_name: None, unique_key: val1}]



Special note about Managed target device
----------------------------------------
Remember that in the case where another Cinder backend is
used that it's likely you'll still need some special data
to instruct the primary driver how to communicate with the
secondary.  In this case we use the same structure and entries
but we set the key **managed_backend_name** to a valid
Cinder backend name.

**WARNING**
The building of the host string for a driver is not always
very straight forward.  The enabled_backends names which
correspond to the driver-section are what actually get used
to form the host string for the volume service.

Also, take care that your driver knows how to parse out the
host correctly, although the secondary backend may be managed
it may not be on the same host, it may have a pool specification
etc.  In the example above we can assume the same host, in other
cases we would need to use the form::

    <host>@<driver-section-name>

and for some vendors we may require pool specification::

    <host>@<driver-section-name>#<pool-name>

Regardless, it's best that you actually check the services entry
and verify that you've set this correctly, and likely to avoid
problems your vendor documentation for customers to configure this
should recommend configuring backends, then verifying settings
from cinder services list.

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

If you needed to provide a specific backend device (multiple backends supporting replication)::
    {replication: enabled, volume_backend_name: foo}

Additionally you could provide additional details using scoped keys::
    {replication: enabled, volume_backend_name: foo,
     replication: replication_type: async}

Again, it's up to the driver to parse the volume type info on create and set things up
as requested.  While the scoping key can be anything, it's strongly recommended that all
backends utilize the same key (replication) for consistency and to make things easier for
the Cloud Administrator.

Capabilities reporting
----------------------
The following entries are expected to be added to the stats/capabilities update for
replication configured devices::

    stats["replication_enabled"] = True|False
    stats["replication_type"] = ['async', 'sync'...]
    stats["replication_count"] = len(self.cluster_pairs)

Required methods
-----------------
The number of API methods associated with replication are intentionally very limited, and are
Admin only methods.

They include::
    replication_enable(self, context, volume)
    replication_disable(self, context, volume)
    replication_failover(self, context, volume)
    list_replication_targets(self, context)

**replication_enable**

Used to notify the driver that we would like to enable replication on a replication capable volume.
NOTE this is NOT used as the initial create replication command, that's handled by the volume-type at
create time.  This is provided as a method for an Admin that may have needed to disable replication
on a volume for maintenance or whatever reason to signify that they'd like to "resume" replication on
the given volume.

**replication_disable**

Used to notify the driver that we would like to disable replication on a replication capable volume.
This again would be used by a Cloud Administrator for things like maintenance etc.

**replication_failover**

Used to instruct the backend to fail over to the secondary/target device on a replication capable volume.
This may be used for triggering a fail-over manually or for testing purposes.

Note that ideally drivers will know how to update the volume reference properly so that Cinder is now
pointing to the secondary.  Also, while it's not required, at this time; ideally the command would
act as a toggle, allowing to switch back and forth betweeen primary and secondary and back to primary.

**list_replication_targets**

Used by the admin to query a volume for a list of configured replication targets
The expected return for this call is expected to mimic the form used in the config file.

For a volume replicating to managed replication targets::

    {'volume_id': volume['id'], 'targets':[{'type': 'managed',
                                            'backend_name': 'backend_name'}...]

For a volume replicating to external/unmanaged targets::

    {'volume_id': volume['id'], 'targets':[{'type': 'unmanaged',
                                            'san_ip': '127.0.0.1',
                                            'san_login': 'admin'...}...]

