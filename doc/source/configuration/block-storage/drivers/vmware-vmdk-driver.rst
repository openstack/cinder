.. _block_storage_vmdk_driver:

==================
VMware VMDK driver
==================

Use the VMware VMDK driver to enable management of the OpenStack Block Storage
volumes on vCenter-managed data stores. Volumes are backed by VMDK files on
data stores that use any VMware-compatible storage technology such as NFS,
iSCSI, FiberChannel, and vSAN.

.. note::

   The VMware VMDK driver requires vCenter version 5.1 at minimum.

Functional context
~~~~~~~~~~~~~~~~~~

The VMware VMDK driver connects to vCenter, through which it can dynamically
access all the data stores visible from the ESX hosts in the managed cluster.

When you create a volume, the VMDK driver creates a VMDK file on demand.  The
VMDK file creation completes only when the volume is subsequently attached to
an instance. The reason for this requirement is that data stores visible to the
instance determine where to place the volume.  Before the service creates the
VMDK file, attach a volume to the target instance.

The running vSphere VM is automatically reconfigured to attach the VMDK file as
an extra disk. Once attached, you can log in to the running vSphere VM to
rescan and discover this extra disk.

With the update to ESX version 6.0, the VMDK driver now supports NFS version
4.1.

Configuration
~~~~~~~~~~~~~

The recommended volume driver for OpenStack Block Storage is the VMware vCenter
VMDK driver. When you configure the driver, you must match it with the
appropriate OpenStack Compute driver from VMware and both drivers must point to
the same server.

In the ``nova.conf`` file, use this option to define the Compute driver:

.. code-block:: ini

   compute_driver = vmwareapi.VMwareVCDriver

In the ``cinder.conf`` file, use this option to define the volume
driver:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver

The following table lists various options that the drivers support for the
OpenStack Block Storage configuration (``cinder.conf``):

.. include:: ../../tables/cinder-vmware.inc

VMDK disk type
~~~~~~~~~~~~~~

The VMware VMDK drivers support the creation of VMDK disk file types ``thin``,
``lazyZeroedThick`` (sometimes called thick or flat), or ``eagerZeroedThick``.

A thin virtual disk is allocated and zeroed on demand as the space is used.
Unused space on a Thin disk is available to other users.

A lazy zeroed thick virtual disk will have all space allocated at disk
creation. This reserves the entire disk space, so it is not available to other
users at any time.

An eager zeroed thick virtual disk is similar to a lazy zeroed thick disk, in
that the entire disk is allocated at creation. However, in this type, any
previous data will be wiped clean on the disk before the write. This can mean
that the disk will take longer to create, but can also prevent issues with
stale data on physical media.

Use the ``vmware:vmdk_type`` extra spec key with the appropriate value to
specify the VMDK disk file type. This table shows the mapping between the extra
spec entry and the VMDK disk file type:

.. list-table:: Extra spec entry to VMDK disk file type mapping
   :header-rows: 1

   * - Disk file type
     - Extra spec key
     - Extra spec value
   * - thin
     - ``vmware:vmdk_type``
     - ``thin``
   * - lazyZeroedThick
     - ``vmware:vmdk_type``
     - ``thick``
   * - eagerZeroedThick
     - ``vmware:vmdk_type``
     - ``eagerZeroedThick``

If you do not specify a ``vmdk_type`` extra spec entry, the disk file type will
default to ``thin``.

The following example shows how to create a ``lazyZeroedThick`` VMDK volume by
using the appropriate ``vmdk_type``:

.. code-block:: console

   $ openstack volume type create THICK_VOLUME
   $ openstack volume type set --property vmware:vmdk_type=thick THICK_VOLUME
   $ openstack volume create --size 1 --type THICK_VOLUME VOLUME1

Clone type
~~~~~~~~~~

With the VMware VMDK drivers, you can create a volume from another
source volume or a snapshot point. The VMware vCenter VMDK driver
supports the ``full`` and ``linked/fast`` clone types. Use the
``vmware:clone_type`` extra spec key to specify the clone type. The
following table captures the mapping for clone types:

.. list-table:: Extra spec entry to clone type mapping
   :header-rows: 1

   * - Clone type
     - Extra spec key
     - Extra spec value
   * - full
     - ``vmware:clone_type``
     - ``full``
   * - linked/fast
     - ``vmware:clone_type``
     - ``linked``

If you do not specify the clone type, the default is ``full``.

The following example shows linked cloning from a source volume, which is
created from an image:

.. code-block:: console

   $ openstack volume type create FAST_CLONE
   $ openstack volume type set --property vmware:clone_type=linked FAST_CLONE
   $ openstack volume create --size 1 --type FAST_CLONE --image MYIMAGE SOURCE_VOL
   $ openstack volume create --size 1 --source SOURCE_VOL DEST_VOL

Adapter type
~~~~~~~~~~~~

The VMware vCenter VMDK driver supports the adapter types ``LSI Logic Parallel``,
``BusLogic Parallel``, ``LSI Logic SAS``, ``VMware Paravirtual`` and ``IDE`` for
volumes. Use the ``vmware:adapter_type`` extra spec key to specify the adapter
type. The following table captures the mapping for adapter types:

.. list-table:: Extra spec entry to adapter type mapping
   :header-rows: 1

   * - Adapter type
     - Extra spec key
     - Extra spec value
   * - BusLogic Parallel
     - ``vmware:adapter_type``
     - ``busLogic``
   * - IDE
     - ``vmware:adapter_type``
     - ``ide``
   * - LSI Logic Parallel
     - ``vmware:adapter_type``
     - ``lsiLogic``
   * - LSI Logic SAS
     - ``vmware:adapter_type``
     - ``lsiLogicsas``
   * - VMware Paravirtual
     - ``vmware:adapter_type``
     - ``paraVirtual``

If you do not specify the adapter type, the default is the value specified by
the config option ``vmware_adapter_type``.

Use vCenter storage policies to specify back-end data stores
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section describes how to configure back-end data stores using storage
policies. In vCenter 5.5 and greater, you can create one or more storage
policies and expose them as a Block Storage volume-type to a vmdk volume. The
storage policies are exposed to the vmdk driver through the extra spec property
with the ``vmware:storage_profile`` key.

For example, assume a storage policy in vCenter named ``gold_policy.`` and a
Block Storage volume type named ``vol1`` with the extra spec key
``vmware:storage_profile`` set to the value ``gold_policy``. Any Block Storage
volume creation that uses the ``vol1`` volume type places the volume only in
data stores that match the ``gold_policy`` storage policy.

The Block Storage back-end configuration for vSphere data stores is
automatically determined based on the vCenter configuration. If you configure a
connection to connect to vCenter version 5.5 or later in the ``cinder.conf``
file, the use of storage policies to configure back-end data stores is
automatically supported.

.. note::

   You must configure any data stores that you configure for the Block
   Storage service for the Compute service.

**To configure back-end data stores by using storage policies**

#. In vCenter, tag the data stores to be used for the back end.

   OpenStack also supports policies that are created by using vendor-specific
   capabilities; for example vSAN-specific storage policies.

   .. note::

      The tag value serves as the policy. For details, see :ref:`vmware-spbm`.

#. Set the extra spec key ``vmware:storage_profile`` in the desired Block
   Storage volume types to the policy name that you created in the previous
   step.

#. Optionally, for the ``vmware_host_version`` parameter, enter the version
   number of your vSphere platform. For example, ``5.5``.

   This setting overrides the default location for the corresponding WSDL file.
   Among other scenarios, you can use this setting to prevent WSDL error
   messages during the development phase or to work with a newer version of
   vCenter.

#. Complete the other vCenter configuration parameters as appropriate.

.. note::

   Any volume that is created without an associated policy (that is to say,
   without an associated volume type that specifies ``vmware:storage_profile``
   extra spec), there is no policy-based placement for that volume.

Supported operations
~~~~~~~~~~~~~~~~~~~~

The VMware vCenter VMDK driver supports these operations:

-  Create, delete, attach, and detach volumes.

   .. note::

      When a volume is attached to an instance, a reconfigure operation is
      performed on the instance to add the volume's VMDK to it. The user must
      manually rescan and mount the device from within the guest operating
      system.

-  Create, list, and delete volume snapshots.

   .. note::

      Allowed only if volume is not attached to an instance.

-  Create a volume from a snapshot.

   .. note::

      The vmdk UUID in vCenter will not be set to the volume UUID if the
      vCenter version is 6.0 or above and the extra spec key ``vmware:clone_type``
      in the destination volume type is set to ``linked``.

-  Copy an image to a volume.

   .. note::

      Only images in ``vmdk`` disk format with ``bare`` container format are
      supported. The ``vmware_disktype`` property of the image can be
      ``preallocated``, ``sparse``, ``streamOptimized`` or ``thin``.

-  Copy a volume to an image.

   .. note::

      -  Allowed only if the volume is not attached to an instance.
      -  This operation creates a ``streamOptimized`` disk image.

-  Clone a volume.

   .. note::

      -  Supported only if the source volume is not attached to an instance.
      -  The vmdk UUID in vCenter will not be set to the volume UUID if the
         vCenter version is 6.0 or above and the extra spec key ``vmware:clone_type``
         in the destination volume type is set to ``linked``.

-  Backup a volume.

   .. note::

      This operation creates a backup of the volume in ``streamOptimized``
      disk format.

-  Restore backup to new or existing volume.

   .. note::

      Supported only if the existing volume doesn't contain snapshots.

-  Change the type of a volume.

   .. note::

      This operation is supported only if the volume state is ``available``.

-  Extend a volume.


.. _vmware-spbm:

Storage policy-based configuration in vCenter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can configure Storage Policy-Based Management (SPBM) profiles for vCenter
data stores supporting the Compute, Image service, and Block Storage components
of an OpenStack implementation.

In a vSphere OpenStack deployment, SPBM enables you to delegate several data
stores for storage, which reduces the risk of running out of storage space. The
policy logic selects the data store based on accessibility and available
storage space.

Prerequisites
~~~~~~~~~~~~~

-  Determine the data stores to be used by the SPBM policy.

-  Determine the tag that identifies the data stores in the OpenStack component
   configuration.

-  Create separate policies or sets of data stores for separate
   OpenStack components.

Create storage policies in vCenter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. In vCenter, create the tag that identifies the data stores:

   #. From the :guilabel:`Home` screen, click :guilabel:`Tags`.

   #. Specify a name for the tag.

   #. Specify a tag category. For example, ``spbm-cinder``.

#. Apply the tag to the data stores to be used by the SPBM policy.

   .. note::

      For details about creating tags in vSphere, see the `vSphere
      documentation
      <http://pubs.vmware.com/vsphere-55/index.jsp#com.vmware.vsphere.vcenterhost.doc/GUID-379F40D3-8CD6-449E-89CB-79C4E2683221.html>`__.

#. In vCenter, create a tag-based storage policy that uses one or more tags to
   identify a set of data stores.

   .. note::

      For details about creating storage policies in vSphere, see the `vSphere
      documentation
      <http://pubs.vmware.com/vsphere-55/index.jsp#com.vmware.vsphere.storage.doc/GUID-89091D59-D844-46B2-94C2-35A3961D23E7.html>`__.

Data store selection
~~~~~~~~~~~~~~~~~~~~

If storage policy is enabled, the driver initially selects all the data stores
that match the associated storage policy.

If two or more data stores match the storage policy, the driver chooses a data
store that is connected to the maximum number of hosts.

In case of ties, the driver chooses the data store with lowest space
utilization, where space utilization is defined by the
``(1-freespace/totalspace)`` meters.

These actions reduce the number of volume migrations while attaching the volume
to instances.

The volume must be migrated if the ESX host for the instance cannot access the
data store that contains the volume.
