.. _multi_backend:

====================================
Configure multiple-storage back ends
====================================

When you configure multiple-storage back ends, you can create several
back-end storage solutions that serve the same OpenStack Compute
configuration and one ``cinder-volume`` is launched for each back-end
storage or back-end storage pool.

In a multiple-storage back-end configuration, each back end has a name
(``volume_backend_name``). Several back ends can have the same name.
In that case, the scheduler properly decides which back end the volume
has to be created in.

The name of the back end is declared as an extra-specification of a
volume type (such as, ``volume_backend_name=LVM``). When a volume
is created, the scheduler chooses an appropriate back end to handle the
request, according to the volume type specified by the user.

Enable multiple-storage back ends
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To enable a multiple-storage back ends, you must set the
`enabled_backends` flag in the ``cinder.conf`` file.
This flag defines the names (separated by a comma) of the configuration
groups for the different back ends: one name is associated to one
configuration group for a back end (such as, ``[lvmdriver-1]``).

.. note::

   The configuration group name is not related to the ``volume_backend_name``.

.. note::

   After setting the ``enabled_backends`` flag on an existing cinder
   service, and restarting the Block Storage services, the original ``host``
   service is replaced with a new host service. The new service appears
   with a name like ``host@backend``. Use:

   .. code-block:: console

      $ cinder-manage volume update_host --currenthost CURRENTHOST --newhost CURRENTHOST@BACKEND

   to convert current block devices to the new host name.

The options for a configuration group must be defined in the group
(or default options are used). All the standard Block Storage
configuration options (``volume_group``, ``volume_driver``, and so on)
might be used in a configuration group. Configuration values in
the ``[DEFAULT]`` configuration group are not used.

These examples show three back ends:

.. code-block:: ini

   enabled_backends=lvmdriver-1,lvmdriver-2,lvmdriver-3
   [lvmdriver-1]
   volume_group=cinder-volumes-1
   volume_driver=cinder.volume.drivers.lvm.LVMVolumeDriver
   volume_backend_name=LVM
   [lvmdriver-2]
   volume_group=cinder-volumes-2
   volume_driver=cinder.volume.drivers.lvm.LVMVolumeDriver
   volume_backend_name=LVM
   [lvmdriver-3]
   volume_group=cinder-volumes-3
   volume_driver=cinder.volume.drivers.lvm.LVMVolumeDriver
   volume_backend_name=LVM_b

In this configuration, ``lvmdriver-1`` and ``lvmdriver-2`` have the same
``volume_backend_name``. If a volume creation requests the ``LVM``
back end name, the scheduler uses the capacity filter scheduler to choose
the most suitable driver, which is either ``lvmdriver-1`` or ``lvmdriver-2``.
The capacity filter scheduler is enabled by default. The next section
provides more information. In addition, this example presents a
``lvmdriver-3`` back end.

.. note::

   For Fiber Channel drivers that support multipath, the configuration group
   requires the ``use_multipath_for_image_xfer=true`` option. In
   the example below, you can see details for HPE 3PAR and EMC Fiber
   Channel drivers.

.. code-block:: ini

   [3par]
   use_multipath_for_image_xfer = true
   volume_driver = cinder.volume.drivers.hpe.hpe_3par_fc.HPE3PARFCDriver
   volume_backend_name = 3parfc

   [emc]
   use_multipath_for_image_xfer = true
   volume_driver = cinder.volume.drivers.emc.emc_smis_fc.EMCSMISFCDriver
   volume_backend_name = emcfc

Configure Block Storage scheduler multi back end
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You must enable the `filter_scheduler` option to use
multiple-storage back ends. The filter scheduler:

#. Filters the available back ends. By default, ``AvailabilityZoneFilter``,
   ``CapacityFilter`` and ``CapabilitiesFilter`` are enabled.

#. Weights the previously filtered back ends. By default, the
   `CapacityWeigher` option is enabled. When this option is
   enabled, the filter scheduler assigns the highest weight to back
   ends with the most available capacity.

The scheduler uses filters and weights to pick the best back end to
handle the request. The scheduler uses volume types to explicitly create
volumes on specific back ends. For more information about filter and weighing,
see :ref:`filter_weigh_scheduler`.


Volume type
~~~~~~~~~~~

Before using it, a volume type has to be declared to Block Storage.
This can be done by the following command:

.. code-block:: console

   $ openstack --os-username admin --os-tenant-name admin volume type create lvm

Then, an extra-specification has to be created to link the volume
type to a back end name. Run this command:

.. code-block:: console

   $ openstack --os-username admin --os-tenant-name admin volume type set lvm \
     --property volume_backend_name=LVM_iSCSI

This example creates a ``lvm`` volume type with
``volume_backend_name=LVM_iSCSI`` as extra-specifications.

Create another volume type:

.. code-block:: console

   $ openstack --os-username admin --os-tenant-name admin volume type create lvm_gold

   $ openstack --os-username admin --os-tenant-name admin volume type set lvm_gold \
     --property volume_backend_name=LVM_iSCSI_b

This second volume type is named ``lvm_gold`` and has ``LVM_iSCSI_b`` as
back end name.

.. note::

   To list the extra-specifications, use this command:

   .. code-block:: console

      $ openstack --os-username admin --os-tenant-name admin volume type list --long

.. note::

   If a volume type points to a ``volume_backend_name`` that does not
   exist in the Block Storage configuration, the ``filter_scheduler``
   returns an error that it cannot find a valid host with the suitable
   back end.

Usage
~~~~~

When you create a volume, you must specify the volume type.
The extra-specifications of the volume type are used to determine which
back end has to be used.

.. code-block:: console

   $ openstack volume create --size 1 --type lvm test_multi_backend

Considering the ``cinder.conf`` described previously, the scheduler
creates this volume on ``lvmdriver-1`` or ``lvmdriver-2``.

.. code-block:: console

   $ openstack volume create --size 1 --type lvm_gold test_multi_backend

This second volume is created on ``lvmdriver-3``.
