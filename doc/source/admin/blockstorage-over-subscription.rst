.. _over_subscription:

=====================================
Oversubscription in thin provisioning
=====================================

OpenStack Block Storage enables you to choose a volume back end based on
virtual capacities for thin provisioning using the oversubscription ratio.

A reference implementation is provided for the default LVM driver. The
illustration below uses the LVM driver as an example.

Configure oversubscription settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To support oversubscription in thin provisioning, a flag
``max_over_subscription_ratio`` is introduced into ``cinder.conf``.
This is a float representation of the oversubscription ratio when thin
provisioning is involved. Default ratio is 20.0, meaning provisioned
capacity can be 20 times of the total physical capacity. A ratio of 10.5
means provisioned capacity can be 10.5 times of the total physical capacity.
A ratio of 1.0 means provisioned capacity cannot exceed the total physical
capacity. A ratio lower than 1.0 is ignored and the default value is used
instead.

.. note::

   ``max_over_subscription_ratio`` can be configured for each back end when
   multiple-storage back ends are enabled. It is provided as a reference
   implementation and is used by the LVM driver. However, it is not a
   requirement for a driver to use this option from ``cinder.conf``.

   ``max_over_subscription_ratio`` is for configuring a back end. For a
   driver that supports multiple pools per back end, it can report this
   ratio for each pool. The LVM driver does not support multiple pools.

The existing ``reserved_percentage`` flag is used to prevent over provisioning.
This flag represents the percentage of the back-end capacity that is reserved.

.. note::

   There is a change on how ``reserved_percentage`` is used. It was measured
   against the free capacity in the past. Now it is measured against the total
   capacity.

Capabilities
~~~~~~~~~~~~

Drivers can report the following capabilities for a back end or a pool:

.. code-block:: ini

   thin_provisioning_support = True(or False)
   thick_provisioning_support = True(or False)
   provisioned_capacity_gb = PROVISIONED_CAPACITY
   max_over_subscription_ratio = MAX_RATIO

Where ``PROVISIONED_CAPACITY`` is the apparent allocated space indicating
how much capacity has been provisioned and ``MAX_RATIO`` is the maximum
oversubscription ratio. For the LVM driver, it is
``max_over_subscription_ratio`` in ``cinder.conf``.

Two capabilities are added here to allow a back end or pool to claim support
for thin provisioning, or thick provisioning, or both.

The LVM driver reports ``thin_provisioning_support=True`` and
``thick_provisioning_support=False`` if the ``lvm_type`` flag in
``cinder.conf`` is ``thin``. Otherwise it reports
``thin_provisioning_support=False`` and ``thick_provisioning_support=True``.

Volume type extra specs
~~~~~~~~~~~~~~~~~~~~~~~

If volume type is provided as part of the volume creation request, it can
have the following extra specs defined:

.. code-block:: python

   'capabilities:thin_provisioning_support': '<is> True' or '<is> False'
   'capabilities:thick_provisioning_support': '<is> True' or '<is> False'

.. note::

   ``capabilities`` scope key before ``thin_provisioning_support`` and
   ``thick_provisioning_support`` is not required. So the following works too:

.. code-block:: python

   'thin_provisioning_support': '<is> True' or '<is> False'
   'thick_provisioning_support': '<is> True' or '<is> False'

The above extra specs are used by the scheduler to find a back end that
supports thin provisioning, thick provisioning, or both to match the needs
of a specific volume type.

Volume replication extra specs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

OpenStack Block Storage has the ability to create volume replicas.
Administrators can define a storage policy that includes
replication by adjusting the cinder volume driver. Volume replication
for OpenStack Block Storage helps safeguard OpenStack environments from
data loss during disaster recovery.

To enable replication when creating volume types, configure the cinder
volume with ``capabilities:replication="<is> True"``.

Each volume created with the replication capability set to ``True``
generates a copy of the volume on a storage back end.

One use case for replication involves an OpenStack cloud environment
installed across two data centers located nearby each other. The
distance between the two data centers in this use case is the length of
a city.

At each data center, a cinder host supports the Block Storage service.
Both data centers include storage back ends.

Depending on the storage requirements, there can be one or two cinder
hosts. The administrator accesses the
``/etc/cinder/cinder.conf`` configuration file and sets
``capabilities:replication="<is> True"``.

If one data center experiences a service failure, administrators
can redeploy the VM. The VM will run using a replicated, backed up
volume on a host in the second data center.

Capacity filter
~~~~~~~~~~~~~~~

In the capacity filter, ``max_over_subscription_ratio`` is used when
choosing a back end if ``thin_provisioning_support`` is True and
``max_over_subscription_ratio`` is greater than 1.0.

Capacity weigher
~~~~~~~~~~~~~~~~

In the capacity weigher, virtual free capacity is used for ranking if
``thin_provisioning_support`` is True. Otherwise, real free capacity
will be used as before.
