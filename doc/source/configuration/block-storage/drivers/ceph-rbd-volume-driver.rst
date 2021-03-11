=============================
Ceph RADOS Block Device (RBD)
=============================

If you use KVM, QEMU or Hyper-V as your hypervisor, you can configure the
Compute service to use `Ceph RADOS block devices
(RBD) <https://ceph.com/ceph-storage/block-storage/>`__ for volumes.

Ceph is a massively scalable, open source, distributed storage system.
It is comprised of an object store, block store, and a POSIX-compliant
distributed file system. The platform can auto-scale to the exabyte
level and beyond. It runs on commodity hardware, is self-healing and
self-managing, and has no single point of failure. Due to its open-source
nature, you can install and use this portable storage platform in
public or private clouds.

.. figure:: ../../figures/ceph-architecture.png

    Ceph architecture

.. note::
   **Supported Ceph versions**

   The current `release cycle model for Ceph
   <https://docs.ceph.com/en/latest/releases/general/>`_
   targets a new release yearly on 1 March, with there being at most
   two active stable releases at any time.

   For a given OpenStack release, *Cinder supports the current Ceph
   active stable releases plus the two prior releases.*

   For example, at the time of the OpenStack Wallaby release in
   April 2021, the Ceph active supported releases are Pacific and
   Octopus.  The Cinder Wallaby release therefore supports Ceph
   Pacific, Octopus, Nautilus, and Mimic.

   Additionally, it is expected that the version of the Ceph client
   available to Cinder or any of its associated libraries (os-brick,
   cinderlib) is aligned with the Ceph server version.  Mixing server
   and client versions is *unsupported* and may lead to anomalous behavior.

   The minimum requirements for using Ceph with Hyper-V are Ceph Pacific and
   Windows Server 2016.

RADOS
~~~~~

Ceph is based on Reliable Autonomic Distributed Object Store (RADOS).
RADOS distributes objects across the storage cluster and replicates
objects for fault tolerance. RADOS contains the following major
components:

*Object Storage Device (OSD) Daemon*
 The storage daemon for the RADOS service, which interacts with the
 OSD (physical or logical storage unit for your data).
 You must run this daemon on each server in your cluster. For each
 OSD, you can have an associated hard drive disk. For performance
 purposes, pool your hard drive disk with raid arrays, or logical volume
 management (LVM). By default, the following pools are created: data,
 metadata, and RBD.

*Meta-Data Server (MDS)*
 Stores metadata. MDSs build a POSIX file
 system on top of objects for Ceph clients. However, if you do not use
 the Ceph file system, you do not need a metadata server.

*Monitor (MON)*
 A lightweight daemon that handles all communications
 with external applications and clients. It also provides a consensus
 for distributed decision making in a Ceph/RADOS cluster. For
 instance, when you mount a Ceph shared on a client, you point to the
 address of a MON server. It checks the state and the consistency of
 the data. In an ideal setup, you must run at least three ``ceph-mon``
 daemons on separate servers.

Ways to store, use, and expose data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To store and access your data, you can use the following storage
systems:

*RADOS*
 Use as an object, default storage mechanism.

*RBD*
 Use as a block device. The Linux kernel RBD (RADOS block
 device) driver allows striping a Linux block device over multiple
 distributed object store data objects. It is compatible with the KVM
 RBD image.

*CephFS*
 Use as a file, POSIX-compliant file system.

Ceph exposes RADOS; you can access it through the following interfaces:

*RADOS Gateway*
 OpenStack Object Storage and Amazon-S3 compatible
 RESTful interface (see `RADOS_Gateway
 <http://docs.ceph.com/docs/master/radosgw/>`__).

*librados*
 and its related C/C++ bindings

*RBD and QEMU-RBD*
 Linux kernel and QEMU block devices that stripe
 data across multiple objects.

RBD pool
~~~~~~~~

The RBD pool used by the Cinder backend is configured with option ``rbd_pool``,
and by default the driver expects exclusive management access to that pool, as
in being the only system creating and deleting resources in it, since that's
the recommended deployment choice.

Pool sharing is strongly discouraged, and if we were to share the pool with
other services, within OpenStack (Nova, Glance, another Cinder backend) or
outside of OpenStack (oVirt), then the stats returned by the driver to the
scheduler would not be entirely accurate.

The inaccuracy would be that the actual size in use by the cinder volumes would
be lower than the reported one, since it would be also including the used space
by the other services.

We can set the ``rbd_exclusive_cinder_pool`` configuration option to ``false``
to fix this inaccuracy, but this has a performance impact.

.. warning::

   Setting ``rbd_exclusive_cinder_pool`` to ``false`` will increase the burden
   on the Cinder driver and the Ceph cluster, since a request will be made for
   each existing image, to retrieve its size, during the stats gathering
   process.

   For deployments with large amount of volumes it is recommended to leave the
   default value of ``true``, and accept the inaccuracy, as it should not be
   particularly problematic.

Driver options
~~~~~~~~~~~~~~

The following table contains the configuration options supported by the
Ceph RADOS Block Device driver.

.. config-table::
   :config-target: Ceph storage

   cinder.volume.drivers.rbd
