================================
IBM Spectrum Scale volume driver
================================
IBM Spectrum Scale is a flexible software-defined storage that can be
deployed as high performance file storage or a cost optimized
large-scale content repository. IBM Spectrum Scale, previously known as
IBM General Parallel File System (GPFS), is designed to scale performance
and capacity with no bottlenecks. IBM Spectrum Scale is a cluster file system
that provides concurrent access to file systems from multiple nodes. The
storage provided by these nodes can be direct attached, network attached,
SAN attached, or a combination of these methods. Spectrum Scale provides
many features beyond common data access, including data replication,
policy based storage management, and space efficient file snapshot and
clone operations.

How the Spectrum Scale volume driver works
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Spectrum Scale volume driver, named ``gpfs.py``, enables the use of
Spectrum Scale in a fashion similar to that of the NFS driver. With
the Spectrum Scale driver, instances do not actually access a storage
device at the block level. Instead, volume backing files are created
in a Spectrum Scale file system and mapped to instances, which emulate
a block device.

.. note::

   Spectrum Scale must be installed and cluster has to be created on the
   storage nodes in the OpenStack environment. A file system must also be
   created and mounted on these nodes before configuring the cinder service
   to use Spectrum Scale storage.For more details, please refer to
   `Spectrum Scale product documentation <https://ibm.biz/Bdi84g>`_.

Optionally, the Image service can be configured to store glance images
in a Spectrum Scale file system. When a Block Storage volume is created
from an image, if both image data and volume data reside in the same
Spectrum Scale file system, the data from image file is moved efficiently
to the volume file using copy-on-write optimization strategy.

Supported operations
~~~~~~~~~~~~~~~~~~~~
- Create, delete, attach, and detach volumes.
- Create, delete volume snapshots.
- Create a volume from a snapshot.
- Create cloned volumes.
- Extend a volume.
- Migrate a volume.
- Retype a volume.
- Create, delete consistency groups.
- Create, delete consistency group snapshots.
- Copy an image to a volume.
- Copy a volume to an image.
- Backup and restore volumes.

Driver configurations
~~~~~~~~~~~~~~~~~~~~~

The Spectrum Scale volume driver supports three modes of deployment.

Mode 1 – Pervasive Spectrum Scale Client
----------------------------------------

When Spectrum Scale is running on compute nodes as well as on the cinder node.
For example, Spectrum Scale filesystem is available to both Compute and
Block Storage services as a local filesystem.

To use Spectrum Scale driver in this deployment mode, set the ``volume_driver``
in the ``cinder.conf`` as:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.ibm.gpfs.GPFSDriver

The following table contains the configuration options supported by the
Spectrum Scale driver in this deployment mode.

.. include:: ../../tables/cinder-ibm_gpfs.inc

.. note::

   The ``gpfs_images_share_mode`` flag is only valid if the Image
   Service is configured to use Spectrum Scale with the
   ``gpfs_images_dir`` flag. When the value of this flag is
   ``copy_on_write``, the paths specified by the ``gpfs_mount_point_base``
   and ``gpfs_images_dir`` flags must both reside in the same GPFS
   file system and in the same GPFS file set.

Mode 2 – Remote Spectrum Scale Driver with Local Compute Access
---------------------------------------------------------------

When Spectrum Scale is running on compute nodes, but not on the Block Storage
node. For example, Spectrum Scale filesystem is only available to Compute
service as Local filesystem where as Block Storage service accesses Spectrum
Scale remotely. In this case, ``cinder-volume`` service running Spectrum Scale
driver access storage system over SSH and creates volume backing files to make
them available on the compute nodes. This mode is typically deployed when the
cinder and glance services are running inside a Linux container. The container
host should have Spectrum Scale client running and GPFS filesystem mount path
should be bind mounted into the Linux containers.

.. note::

   Note that the user IDs present in the containers should match as that in the
   host machines. For example, the containers running cinder and glance
   services should be priviledged containers.

To use Spectrum Scale driver in this deployment mode, set the ``volume_driver``
in the ``cinder.conf`` as:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.ibm.gpfs.GPFSRemoteDriver

The following table contains the configuration options supported by the
Spectrum Scale driver in this deployment mode.

.. include:: ../../tables/cinder-ibm_gpfs_remote.inc

.. note::

   The ``gpfs_images_share_mode`` flag is only valid if the Image
   Service is configured to use Spectrum Scale with the
   ``gpfs_images_dir`` flag. When the value of this flag is
   ``copy_on_write``, the paths specified by the ``gpfs_mount_point_base``
   and ``gpfs_images_dir`` flags must both reside in the same GPFS
   file system and in the same GPFS file set.

Mode 3 – Remote Spectrum Scale Access
-------------------------------------

When both Compute and Block Storage nodes are not running Spectrum Scale
software and do not have access to Spectrum Scale file system directly as
local filesystem. In this case, we create an NFS export on the volume path
and make it available on the cinder node and on compute nodes.

Optionally, if one wants to use the copy-on-write optimization to create
bootable volumes from glance images, one need to also export the glance
images path and mount it on the nodes where glance and cinder services
are running. The cinder and glance services will access the GPFS
filesystem through NFS.

To use Spectrum Scale driver in this deployment mode, set the ``volume_driver``
in the ``cinder.conf`` as:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.ibm.gpfs.GPFSNFSDriver

The following table contains the configuration options supported by the
Spectrum Scale driver in this deployment mode.

.. include:: ../../tables/cinder-ibm_gpfs_nfs.inc

Additionally, all the options of the base NFS driver are applicable
for GPFSNFSDriver. The above table lists the basic configuration
options which are needed for initialization of the driver.

.. note::

   The ``gpfs_images_share_mode`` flag is only valid if the Image
   Service is configured to use Spectrum Scale with the
   ``gpfs_images_dir`` flag. When the value of this flag is
   ``copy_on_write``, the paths specified by the ``gpfs_mount_point_base``
   and ``gpfs_images_dir`` flags must both reside in the same GPFS
   file system and in the same GPFS file set.


Volume creation options
~~~~~~~~~~~~~~~~~~~~~~~

It is possible to specify additional volume configuration options on a
per-volume basis by specifying volume metadata. The volume is created
using the specified options. Changing the metadata after the volume is
created has no effect. The following table lists the volume creation
options supported by the GPFS volume driver.

.. list-table:: **Volume Create Options for Spectrum Scale Volume Drivers**
   :widths: 10 25
   :header-rows: 1

   * - Metadata Item Name
     - Description
   * - fstype
     - Specifies whether to create a file system or a swap area on the new volume. If fstype=swap is specified, the mkswap command is used to create a swap area. Otherwise the mkfs command is passed the specified file system type, for example ext3, ext4 or ntfs.
   * - fslabel
     - Sets the file system label for the file system specified by fstype option. This value is only used if fstype is specified.
   * - data_pool_name
     - Specifies the GPFS storage pool to which the volume is to be assigned. Note: The GPFS storage pool must already have been created.
   * - replicas
     - Specifies how many copies of the volume file to create. Valid values are 1, 2, and, for Spectrum Scale V3.5.0.7 and later, 3. This value cannot be greater than the value of the MaxDataReplicasattribute of the file system.
   * - dio
     - Enables or disables the Direct I/O caching policy for the volume file. Valid values are yes and no.
   * - write_affinity_depth
     - Specifies the allocation policy to be used for the volume file. Note: This option only works if allow-write-affinity is set for the GPFS data pool.
   * - block_group_factor
     - Specifies how many blocks are laid out sequentially in the volume file to behave as a single large block. Note: This option only works if allow-write-affinity is set for the GPFS data pool.
   * - write_affinity_failure_group
     - Specifies the range of nodes (in GPFS shared nothing architecture) where replicas of blocks in the volume file are to be written. See Spectrum Scale documentation for more details about this option.

This example shows the creation of a 50GB volume with an ``ext4`` file
system labeled ``newfs`` and direct IO enabled:

.. code-block:: console

   $ openstack volume create --property fstype=ext4 fslabel=newfs dio=yes \
     --size 50 VOLUME

Note that if the metadata for the volume is changed later, the changes
do not reflect in the backend. User will have to manually change the
volume attributes corresponding to metadata on Spectrum Scale filesystem.

Operational notes for GPFS driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Volume snapshots are implemented using the GPFS file clone feature.
Whenever a new snapshot is created, the snapshot file is efficiently
created as a read-only clone parent of the volume, and the volume file
uses copy-on-write optimization strategy to minimize data movement.

Similarly when a new volume is created from a snapshot or from an
existing volume, the same approach is taken. The same approach is also
used when a new volume is created from an Image service image, if the
source image is in raw format, and ``gpfs_images_share_mode`` is set to
``copy_on_write``.

The Spectrum Scale driver supports encrypted volume back end feature.
To encrypt a volume at rest, specify the extra specification
``gpfs_encryption_rest = True``.
