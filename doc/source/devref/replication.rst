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
devices for a specific driver.  There are two types of target
devices that can be configured:

   1. Cinder Managed (represented by the volume-backend name)
   2. External devices (require vendor specific data to configure)

NOTE that it is expected to be an error to have both managed and unmanaged replication
config variables set for a single driver.

Cinder managed target device
-----------------------------

In the case of a Cinder managed target device, we simply
use another Cinder configured backend as the replication
target.

For example if we have two backend devices foo and biz that
can replicate to each other, we can set up backend biz as
a replication target for device foo using the following
config entries::

    .....
    [driver-biz]
    volume_driver=xxxx
    volume_backend_name=biz

    [driver-foo]
    volume_driver=xxxx
    volume_backend_name=foo
    managed_replication_target=True
    replication_devices=volume_backend_name-1,volume_backend_name-2....

Notice that the only change from the usual driver configuration
section here is the addition of the replication_devices option.


Unmanaged target device
------------------------

In some cases the replication target device may not be a
configured Cinder backend.  In this case it's the configured
drivers responsibility to route commands to the active device
and to update provider info to ensure the proper iSCSI targets
are being used.

This type of config changes only slightly, and instead of using
a backend_name, it takes the vendor unique config options::

    .....
    [driver-foo]
    volume_driver=xxxx
    volume_backend_name=foo
    managed_replication_target=False
    replication_devices={'key1'='val1' 'key2'='val2' ...},
                        {'key7'='val7'....},...

Note the key/value entries can be whatever the device requires, we treat the actual
variable in the config parser as a comma delimited list, the {} and = notations are
convenient/common parser delimeters, and the K/V entries are space seperated.

We provide a literal evaluator to convert these entries into a proper dict, thus
format is extremely important here.


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
     replication:replication_type: async}

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
The expected return for this call is expeceted to mimic the form used in the config file.

For a volume replicating to managed replication targets::

    {'volume_id': volume['id'], 'targets':[{'type': 'managed',
                                            'backend_name': 'backend_name'}...]

For a volume replicating to external/unmanaged targets::

    {'volume_id': volume['id'], 'targets':[{'type': 'unmanaged',
                                            'san_ip': '127.0.0.1',
                                            'san_login': 'admin'...}...]

