==============
Manage volumes
==============

The default OpenStack Block Storage service implementation is an
iSCSI solution that uses :term:`Logical Volume Manager (LVM)` for Linux.

.. note::

   The OpenStack Block Storage service is not a shared storage
   solution like a Network Attached Storage (NAS) of NFS volumes
   where you can attach a volume to multiple servers. With the
   OpenStack Block Storage service, you can attach a volume to only
   one instance at a time.

   The OpenStack Block Storage service also provides drivers that
   enable you to use several vendors' back-end storage devices in
   addition to the base LVM implementation.  These storage devices can
   also be used instead of the base LVM installation.

This high-level procedure shows you how to create and attach a volume
to a server instance.

**To create and attach a volume to an instance**

#. Configure the OpenStack Compute and the OpenStack Block Storage
   services through the ``/etc/cinder/cinder.conf`` file.
#. Use the :command:`openstack volume create` command to create a volume.
   This command creates an LV into the volume group (VG) ``cinder-volumes``.
#. Use the :command:`openstack server add volume` command to attach the
   volume to an instance. This command creates a unique :term:`IQN <iSCSI
   Qualified Name (IQN)>` that is exposed to the compute node.

   * The compute node, which runs the instance, now has an active
     iSCSI session and new local storage (usually a ``/dev/sdX``
     disk).
   * Libvirt uses that local storage as storage for the instance. The
     instance gets a new disk (usually a ``/dev/vdX`` disk).

For this particular walkthrough, one cloud controller runs
``nova-api``, ``nova-scheduler``, ``nova-objectstore``,
``nova-network`` and ``cinder-*`` services. Two additional compute
nodes run ``nova-compute``. The walkthrough uses a custom
partitioning scheme that carves out 60 GB of space and labels it as
LVM. The network uses the ``FlatManager`` and ``NetworkManager``
settings for OpenStack Compute.

The network mode does not interfere with OpenStack Block Storage
operations, but you must set up networking for Block Storage to work.
For details, see `networking`_.

.. _networking: https://docs.openstack.org/neutron/latest/

To set up Compute to use volumes, ensure that Block Storage is
installed along with ``lvm2``. This guide describes how to
troubleshoot your installation and back up your Compute volumes.

.. toctree::

   blockstorage-boot-from-volume.rst
   blockstorage-nfs-backend.rst
   blockstorage-glusterfs-backend.rst
   blockstorage-multi-backend.rst
   blockstorage-backup-disks.rst
   blockstorage-volume-migration.rst
   blockstorage-glusterfs-removal.rst
   blockstorage-volume-backups.rst
   blockstorage-volume-backups-export-import.rst
   blockstorage-lio-iscsi-support.rst
   blockstorage-volume-number-weigher.rst
   blockstorage-consistency-groups.rst
   blockstorage-driver-filter-weighing.rst
   blockstorage-ratelimit-volume-copy-bandwidth.rst
   blockstorage-over-subscription.rst
   blockstorage-image-volume-cache.rst
   blockstorage-volume-backed-image.rst
   blockstorage-get-capabilities.rst
   blockstorage-groups.rst

.. note::

   To enable the use of encrypted volumes, see the setup instructions in
   `Create an encrypted volume type
   <https://docs.openstack.org/admin-guide/dashboard-manage-volumes.html#create-an-encrypted-volume-type>`_.
