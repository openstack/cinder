=============================
Ceph RADOS Block Device (RBD)
=============================

If you use KVM or QEMU as your hypervisor, you can configure the Compute
service to use `Ceph RADOS block devices
(RBD) <http://ceph.com/ceph-storage/block-storage/>`__ for volumes.

Ceph is a massively scalable, open source, distributed storage system.
It is comprised of an object store, block store, and a POSIX-compliant
distributed file system. The platform can auto-scale to the exabyte
level and beyond. It runs on commodity hardware, is self-healing and
self-managing, and has no single point of failure. Ceph is in the Linux
kernel and is integrated with the OpenStack cloud operating system. Due
to its open-source nature, you can install and use this portable storage
platform in public or private clouds.

.. figure:: ../../figures/ceph-architecture.png

    Ceph architecture

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
 purposes, pool your hard drive disk with raid arrays, logical volume
 management (LVM), or B-tree file system (Btrfs) pooling. By default,
 the following pools are created: data, metadata, and RBD.

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

Ceph developers recommend XFS for production deployments, Btrfs for
testing, development, and any non-critical deployments. Btrfs has the
correct feature set and roadmap to serve Ceph in the long-term, but XFS
and ext4 provide the necessary stability for today’s deployments.

.. note::

   If using Btrfs, ensure that you use the correct version (see `Ceph
   Dependencies <http://ceph.com/docs/master/start/os-recommendations/.>`__).

   For more information about usable file systems, see
   `ceph.com/ceph-storage/file-system/ <http://ceph.com/ceph-storage/file-system/>`__.

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
 <http://ceph.com/wiki/RADOS_Gateway>`__).

*librados*
 and its related C/C++ bindings

*RBD and QEMU-RBD*
 Linux kernel and QEMU block devices that stripe
 data across multiple objects.

Driver options
~~~~~~~~~~~~~~

The following table contains the configuration options supported by the
Ceph RADOS Block Device driver.

.. note::

   The ``volume_tmp_dir`` option has been deprecated and replaced by
   ``image_conversion_dir``.

.. include:: ../../tables/cinder-storage_ceph.inc
