.. _filter_weigh_scheduler:

==========================================================
Configure and use driver filter and weighing for scheduler
==========================================================

OpenStack Block Storage enables you to choose a volume back end based on
back-end specific properties by using the DriverFilter and
GoodnessWeigher for the scheduler. The driver filter and weigher
scheduling can help ensure that the scheduler chooses the best back end
based on requested volume properties as well as various back-end
specific properties.

What is driver filter and weigher and when to use it
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The driver filter and weigher gives you the ability to more finely
control how the OpenStack Block Storage scheduler chooses the best back
end to use when handling a volume request. One example scenario where
using the driver filter and weigher can be if a back end that utilizes
thin-provisioning is used. The default filters use the ``free capacity``
property to determine the best back end, but that is not always perfect.
If a back end has the ability to provide a more accurate back-end
specific value you can use that as part of the weighing. Another example
of when the driver filter and weigher can prove useful is if a back end
exists where there is a hard limit of 1000 volumes. The maximum volume
size is 500 GB. Once 75% of the total space is occupied the performance
of the back end degrades. The driver filter and weigher can provide a
way for these limits to be checked for.

Enable driver filter and weighing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To enable the driver filter, set the ``scheduler_default_filters`` option in
the ``cinder.conf`` file to ``DriverFilter`` or add it to the list if
other filters are already present.

To enable the goodness filter as a weigher, set the
``scheduler_default_weighers`` option in the ``cinder.conf`` file to
``GoodnessWeigher`` or add it to the list if other weighers are already
present.

You can choose to use the ``DriverFilter`` without the
``GoodnessWeigher`` or vice-versa. The filter and weigher working
together, however, create the most benefits when helping the scheduler
choose an ideal back end.

.. important::

   The support for the ``DriverFilter`` and ``GoodnessWeigher`` is
   optional for back ends. If you are using a back end that does not
   support the filter and weigher functionality you may not get the
   full benefit.

Example ``cinder.conf`` configuration file:

.. code-block:: ini

   scheduler_default_filters = DriverFilter
   scheduler_default_weighers = GoodnessWeigher

.. note::

   It is useful to use the other filters and weighers available in
   OpenStack in combination with these custom ones. For example, the
   ``CapacityFilter`` and ``CapacityWeigher`` can be combined with
   these.

Defining your own filter and goodness functions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can define your own filter and goodness functions through the use of
various properties that OpenStack Block Storage has exposed. Properties
exposed include information about the volume request being made,
``volume_type`` settings, and back-end specific information about drivers.
All of these allow for a lot of control over how the ideal back end for
a volume request will be decided.

The ``filter_function`` option is a string defining an equation that
will determine whether a back end should be considered as a potential
candidate in the scheduler.

The ``goodness_function`` option is a string defining an equation that
will rate the quality of the potential host (0 to 100, 0 lowest, 100
highest).

.. important::

   The drive filter and weigher will use default values for filter and
   goodness functions for each back end if you do not define them
   yourself. If complete control is desired then a filter and goodness
   function should be defined for each of the back ends in
   the ``cinder.conf`` file.


Supported operations in filter and goodness functions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Below is a table of all the operations currently usable in custom filter
and goodness functions created by you:

+--------------------------------+-------------------------+
| Operations                     | Type                    |
+================================+=========================+
| +, -, \*, /, ^                 | standard math           |
+--------------------------------+-------------------------+
| not, and, or, &, \|, !         | logic                   |
+--------------------------------+-------------------------+
| >, >=, <, <=, ==, <>, !=       | equality                |
+--------------------------------+-------------------------+
| +, -                           | sign                    |
+--------------------------------+-------------------------+
| x ? a : b                      | ternary                 |
+--------------------------------+-------------------------+
| abs(x), max(x, y), min(x, y)   | math helper functions   |
+--------------------------------+-------------------------+

.. caution::

   Syntax errors you define in filter or goodness strings
   are thrown at a volume request time.

Available properties when creating custom functions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There are various properties that can be used in either the
``filter_function`` or the ``goodness_function`` strings. The properties allow
access to volume info, qos settings, extra specs, and so on.

The following properties and their sub-properties are currently
available for use:

Host stats for a back end
-------------------------
host
    The host's name

volume\_backend\_name
    The volume back end name

vendor\_name
    The vendor name

driver\_version
    The driver version

storage\_protocol
    The storage protocol

QoS\_support
    Boolean signifying whether QoS is supported

total\_capacity\_gb
    The total capacity in GB

allocated\_capacity\_gb
    The allocated capacity in GB

reserved\_percentage
    The reserved storage percentage

Capabilities specific to a back end
-----------------------------------

These properties are determined by the specific back end
you are creating filter and goodness functions for. Some back ends
may not have any properties available here.

Requested volume properties
---------------------------

status
    Status for the requested volume

volume\_type\_id
    The volume type ID

display\_name
    The display name of the volume

volume\_metadata
    Any metadata the volume has

reservations
    Any reservations the volume has

user\_id
    The volume's user ID

attach\_status
    The attach status for the volume

display\_description
    The volume's display description

id
    The volume's ID

replication\_status
    The volume's replication status

snapshot\_id
    The volume's snapshot ID

encryption\_key\_id
    The volume's encryption key ID

source\_volid
    The source volume ID

volume\_admin\_metadata
    Any admin metadata for this volume

source\_replicaid
    The source replication ID

consistencygroup\_id
    The consistency group ID

size
    The size of the volume in GB

metadata
    General metadata

The property most used from here will most likely be the ``size`` sub-property.

Extra specs for the requested volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

View the available properties for volume types by running:

.. code-block:: console

   $ cinder extra-specs-list

Current QoS specs for the requested volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

View the available properties for volume types by running:

.. code-block:: console

   $ openstack volume qos list

In order to access these properties in a custom string use the following
format:

``<property>.<sub_property>``

Driver filter and weigher usage examples
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Below are examples for using the filter and weigher separately,
together, and using driver-specific properties.

Example ``cinder.conf`` file configuration for customizing the filter
function:

.. code-block:: ini

   [default]
   scheduler_default_filters = DriverFilter
   enabled_backends = lvm-1, lvm-2

   [lvm-1]
   volume_driver = cinder.volume.drivers.lvm.LVMVolumeDriver
   volume_backend_name = sample_LVM01
   filter_function = "volume.size < 10"

   [lvm-2]
   volume_driver = cinder.volume.drivers.lvm.LVMVolumeDriver
   volume_backend_name = sample_LVM02
   filter_function = "volume.size >= 10"

The above example will filter volumes to different back ends depending
on the size of the requested volume. Default OpenStack Block Storage
scheduler weighing is done. Volumes with a size less than 10 GB are sent
to lvm-1 and volumes with a size greater than or equal to 10 GB are sent
to lvm-2.

Example ``cinder.conf`` file configuration for customizing the goodness
function:

.. code-block:: ini

   [default]
   scheduler_default_weighers = GoodnessWeigher
   enabled_backends = lvm-1, lvm-2

   [lvm-1]
   volume_driver = cinder.volume.drivers.lvm.LVMVolumeDriver
   volume_backend_name = sample_LVM01
   goodness_function = "(volume.size < 5) ? 100 : 50"

   [lvm-2]
   volume_driver = cinder.volume.drivers.lvm.LVMVolumeDriver
   volume_backend_name = sample_LVM02
   goodness_function = "(volume.size >= 5) ? 100 : 25"

The above example will determine the goodness rating of a back end based
off of the requested volume's size. Default OpenStack Block Storage
scheduler filtering is done. The example shows how the ternary if
statement can be used in a filter or goodness function. If a requested
volume is of size 10 GB then lvm-1 is rated as 50 and lvm-2 is rated as
100. In this case lvm-2 wins. If a requested volume is of size 3 GB then
lvm-1 is rated 100 and lvm-2 is rated 25. In this case lvm-1 would win.

Example ``cinder.conf`` file configuration for customizing both the
filter and goodness functions:

.. code-block:: ini

   [default]
   scheduler_default_filters = DriverFilter
   scheduler_default_weighers = GoodnessWeigher
   enabled_backends = lvm-1, lvm-2

   [lvm-1]
   volume_driver = cinder.volume.drivers.lvm.LVMVolumeDriver
   volume_backend_name = sample_LVM01
   filter_function = "stats.total_capacity_gb < 500"
   goodness_function = "(volume.size < 25) ? 100 : 50"

   [lvm-2]
   volume_driver = cinder.volume.drivers.lvm.LVMVolumeDriver
   volume_backend_name = sample_LVM02
   filter_function = "stats.total_capacity_gb >= 500"
   goodness_function = "(volume.size >= 25) ? 100 : 75"

The above example combines the techniques from the first two examples.
The best back end is now decided based off of the total capacity of the
back end and the requested volume's size.

Example ``cinder.conf`` file configuration for accessing driver specific
properties:

.. code-block:: ini

   [default]
   scheduler_default_filters = DriverFilter
   scheduler_default_weighers = GoodnessWeigher
   enabled_backends = lvm-1,lvm-2,lvm-3

   [lvm-1]
   volume_group = stack-volumes-lvmdriver-1
   volume_driver = cinder.volume.drivers.lvm.LVMVolumeDriver
   volume_backend_name = lvmdriver-1
   filter_function = "volume.size < 5"
   goodness_function = "(capabilities.total_volumes < 3) ? 100 : 50"

   [lvm-2]
   volume_group = stack-volumes-lvmdriver-2
   volume_driver = cinder.volume.drivers.lvm.LVMVolumeDriver
   volume_backend_name = lvmdriver-2
   filter_function = "volumes.size < 5"
   goodness_function = "(capabilities.total_volumes < 8) ? 100 : 50"

   [lvm-3]
   volume_group = stack-volumes-lvmdriver-3
   volume_driver = cinder.volume.drivers.LVMVolumeDriver
   volume_backend_name = lvmdriver-3
   goodness_function = "55"

The above is an example of how back-end specific properties can be used
in the filter and goodness functions. In this example the LVM driver's
``total_volumes`` capability is being used to determine which host gets
used during a volume request. In the above example, lvm-1 and lvm-2 will
handle volume requests for all volumes with a size less than 5 GB. The
lvm-1 host will have priority until it contains three or more volumes.
After than lvm-2 will have priority until it contains eight or more
volumes. The lvm-3 will collect all volumes greater or equal to 5 GB as
well as all volumes once lvm-1 and lvm-2 lose priority.
