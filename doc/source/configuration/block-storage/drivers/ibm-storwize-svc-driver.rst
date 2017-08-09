=========================================
IBM Storwize family and SVC volume driver
=========================================

The volume management driver for Storwize family and SAN Volume
Controller (SVC) provides OpenStack Compute instances with access to IBM
Storwize family or SVC storage systems.

Supported operations
~~~~~~~~~~~~~~~~~~~~

Storwize/SVC driver supports the following Block Storage service volume
operations:

-  Create, list, delete, attach (map), and detach (unmap) volumes.
-  Create, list, and delete volume snapshots.
-  Copy an image to a volume.
-  Copy a volume to an image.
-  Clone a volume.
-  Extend a volume.
-  Retype a volume.
-  Create a volume from a snapshot.
-  Create, list, and delete consistency group.
-  Create, list, and delete consistency group snapshot.
-  Modify consistency group (add or remove volumes).
-  Create consistency group from source (source can be a CG or CG snapshot)
-  Manage an existing volume.
-  Failover-host for replicated back ends.
-  Failback-host for replicated back ends.

Configure the Storwize family and SVC system
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Network configuration
---------------------

The Storwize family or SVC system must be configured for iSCSI, Fibre
Channel, or both.

If using iSCSI, each Storwize family or SVC node should have at least
one iSCSI IP address. The IBM Storwize/SVC driver uses an iSCSI IP
address associated with the volume's preferred node (if available) to
attach the volume to the instance, otherwise it uses the first available
iSCSI IP address of the system. The driver obtains the iSCSI IP address
directly from the storage system. You do not need to provide these iSCSI
IP addresses directly to the driver.

.. note::

   If using iSCSI, ensure that the compute nodes have iSCSI network
   access to the Storwize family or SVC system.

If using Fibre Channel (FC), each Storwize family or SVC node should
have at least one WWPN port configured. The driver uses all available
WWPNs to attach the volume to the instance. The driver obtains the
WWPNs directly from the storage system. You do not need to provide
these WWPNs directly to the driver.

.. note::

   If using FC, ensure that the compute nodes have FC connectivity to
   the Storwize family or SVC system.

iSCSI CHAP authentication
-------------------------

If using iSCSI for data access and the
``storwize_svc_iscsi_chap_enabled`` is set to ``True``, the driver will
associate randomly-generated CHAP secrets with all hosts on the Storwize
family system. The compute nodes use these secrets when creating
iSCSI connections.

.. warning::

   CHAP secrets are added to existing hosts as well as newly-created
   ones. If the CHAP option is enabled, hosts will not be able to
   access the storage without the generated secrets.

.. note::

   Not all OpenStack Compute drivers support CHAP authentication.
   Please check compatibility before using.

.. note::

   CHAP secrets are passed from OpenStack Block Storage to Compute in
   clear text. This communication should be secured to ensure that CHAP
   secrets are not discovered.

Configure storage pools
-----------------------

The IBM Storwize/SVC driver can allocate volumes in multiple pools.
The pools should be created in advance and be provided to the driver
using the ``storwize_svc_volpool_name`` configuration flag in the form
of a comma-separated list.
For the complete list of configuration flags, see :ref:`config_flags`.

Configure user authentication for the driver
--------------------------------------------

The driver requires access to the Storwize family or SVC system
management interface. The driver communicates with the management using
SSH. The driver should be provided with the Storwize family or SVC
management IP using the ``san_ip`` flag, and the management port should
be provided by the ``san_ssh_port`` flag. By default, the port value is
configured to be port 22 (SSH). Also, you can set the secondary
management IP using the ``storwize_san_secondary_ip`` flag.

.. note::

   Make sure the compute node running the cinder-volume management
   driver has SSH network access to the storage system.

To allow the driver to communicate with the Storwize family or SVC
system, you must provide the driver with a user on the storage system.
The driver has two authentication methods: password-based authentication
and SSH key pair authentication. The user should have an Administrator
role. It is suggested to create a new user for the management driver.
Please consult with your storage and security administrator regarding
the preferred authentication method and how passwords or SSH keys should
be stored in a secure manner.

.. note::

   When creating a new user on the Storwize or SVC system, make sure
   the user belongs to the Administrator group or to another group that
   has an Administrator role.

If using password authentication, assign a password to the user on the
Storwize or SVC system. The driver configuration flags for the user and
password are ``san_login`` and ``san_password``, respectively.

If you are using the SSH key pair authentication, create SSH private and
public keys using the instructions below or by any other method.
Associate the public key with the user by uploading the public key:
select the :guilabel:`choose file` option in the Storwize family or SVC
management GUI under :guilabel:`SSH public key`. Alternatively, you may
associate the SSH public key using the command-line interface; details can
be found in the Storwize and SVC documentation. The private key should be
provided to the driver using the ``san_private_key`` configuration flag.

Create a SSH key pair with OpenSSH
----------------------------------

You can create an SSH key pair using OpenSSH, by running:

.. code-block:: console

   $ ssh-keygen -t rsa

The command prompts for a file to save the key pair. For example, if you
select ``key`` as the filename, two files are created: ``key`` and
``key.pub``. The ``key`` file holds the private SSH key and ``key.pub``
holds the public SSH key.

The command also prompts for a pass phrase, which should be empty.

The private key file should be provided to the driver using the
``san_private_key`` configuration flag. The public key should be
uploaded to the Storwize family or SVC system using the storage
management GUI or command-line interface.

.. note::

   Ensure that Cinder has read permissions on the private key file.

Configure the Storwize family and SVC driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Enable the Storwize family and SVC driver
-----------------------------------------

Set the volume driver to the Storwize family and SVC driver by setting
the ``volume_driver`` option in the ``cinder.conf`` file as follows:

iSCSI:

.. code-block:: ini

   [svc1234]
   volume_driver = cinder.volume.drivers.ibm.storwize_svc.storwize_svc_iscsi.StorwizeSVCISCSIDriver
   san_ip = 1.2.3.4
   san_login = superuser
   san_password = passw0rd
   storwize_svc_volpool_name = cinder_pool1
   volume_backend_name = svc1234

FC:

.. code-block:: ini

   [svc1234]
   volume_driver = cinder.volume.drivers.ibm.storwize_svc.storwize_svc_fc.StorwizeSVCFCDriver
   san_ip = 1.2.3.4
   san_login = superuser
   san_password = passw0rd
   storwize_svc_volpool_name = cinder_pool1
   volume_backend_name = svc1234

Replication configuration
-------------------------

Add the following to the back-end specification to specify another storage
to replicate to:

.. code-block:: ini

   replication_device = backend_id:rep_svc,
                        san_ip:1.2.3.5,
                        san_login:superuser,
                        san_password:passw0rd,
                        pool_name:cinder_pool1

The ``backend_id`` is a unique name of the remote storage, the ``san_ip``,
``san_login``, and ``san_password`` is authentication information for the
remote storage. The ``pool_name`` is the pool name for the replication
target volume.

.. note::

   Only one ``replication_device`` can be configured for one back end
   storage since only one replication target is supported now.

.. _config_flags:

Storwize family and SVC driver options in cinder.conf
-----------------------------------------------------

The following options specify default values for all volumes. Some can
be over-ridden using volume types, which are described below.

.. include:: ../../tables/cinder-storwize.inc

Note the following:

* The authentication requires either a password (``san_password``) or
  SSH private key (``san_private_key``). One must be specified. If
  both are specified, the driver uses only the SSH private key.

* The driver creates thin-provisioned volumes by default. The
  ``storwize_svc_vol_rsize`` flag defines the initial physical
  allocation percentage for thin-provisioned volumes, or if set to
  ``-1``, the driver creates full allocated volumes. More details about
  the available options are available in the Storwize family and SVC
  documentation.


Placement with volume types
---------------------------

The IBM Storwize/SVC driver exposes capabilities that can be added to
the ``extra specs`` of volume types, and used by the filter
scheduler to determine placement of new volumes. Make sure to prefix
these keys with ``capabilities:`` to indicate that the scheduler should
use them. The following ``extra specs`` are supported:

-  ``capabilities:volume_backend_name`` - Specify a specific back-end
   where the volume should be created. The back-end name is a
   concatenation of the name of the IBM Storwize/SVC storage system as
   shown in ``lssystem``, an underscore, and the name of the pool (mdisk
   group). For example:

   .. code-block:: ini

      capabilities:volume_backend_name=myV7000_openstackpool

-  ``capabilities:compression_support`` - Specify a back-end according to
   compression support. A value of ``True`` should be used to request a
   back-end that supports compression, and a value of ``False`` will
   request a back-end that does not support compression. If you do not
   have constraints on compression support, do not set this key. Note
   that specifying ``True`` does not enable compression; it only
   requests that the volume be placed on a back-end that supports
   compression. Example syntax:

   .. code-block:: ini

      capabilities:compression_support='<is> True'

-  ``capabilities:easytier_support`` - Similar semantics as the
   ``compression_support`` key, but for specifying according to support
   of the Easy Tier feature. Example syntax:

   .. code-block:: ini

      capabilities:easytier_support='<is> True'

-  ``capabilities:pool_name`` - Specify a specific pool to create volume
   if only multiple pools are configured. pool_name should be one value
   configured in storwize_svc_volpool_name flag. Example syntax:

   .. code-block:: ini

      capabilities:pool_name=cinder_pool2

Configure per-volume creation options
-------------------------------------

Volume types can also be used to pass options to the IBM Storwize/SVC
driver, which over-ride the default values set in the configuration
file. Contrary to the previous examples where the ``capabilities`` scope
was used to pass parameters to the Cinder scheduler, options can be
passed to the IBM Storwize/SVC driver with the ``drivers`` scope.

The following ``extra specs`` keys are supported by the IBM Storwize/SVC
driver:

- rsize
- warning
- autoexpand
- grainsize
- compression
- easytier
- multipath
- iogrp
- mirror_pool

These keys have the same semantics as their counterparts in the
configuration file. They are set similarly; for example, ``rsize=2`` or
``compression=False``.

Example: Volume types
---------------------

In the following example, we create a volume type to specify a
controller that supports compression, and enable compression:

.. code-block:: console

   $ openstack volume type create compressed
   $ openstack volume type set --property capabilities:compression_support='<is> True' --property drivers:compression=True compressed

We can then create a 50GB volume using this type:

.. code-block:: console

   $ openstack volume create "compressed volume" --type compressed --size 50

In the following example, create a volume type that enables
synchronous replication (metro mirror):

.. code-block:: console

   $ openstack volume type create ReplicationType
   $ openstack volume type set --property replication_type="<in> metro" \
     --property replication_enabled='<is> True' --property volume_backend_name=svc234 ReplicationType

In the following example, we create a volume type to support stretch cluster
volume or mirror volume:

.. code-block:: console

   $ openstack volume type create mirror_vol_type
   $ openstack volume type set --property volume_backend_name=svc1 \
     --property drivers:mirror_pool=pool2 mirror_vol_type

Volume types can be used, for example, to provide users with different

-  performance levels (such as, allocating entirely on an HDD tier,
   using Easy Tier for an HDD-SDD mix, or allocating entirely on an SSD
   tier)

-  resiliency levels (such as, allocating volumes in pools with
   different RAID levels)

-  features (such as, enabling/disabling Real-time Compression,
   replication volume creation)

QOS
---

The Storwize driver provides QOS support for storage volumes by
controlling the I/O amount. QOS is enabled by editing the
``etc/cinder/cinder.conf`` file and setting the
``storwize_svc_allow_tenant_qos`` to ``True``.

There are three ways to set the Storwize ``IOThrotting`` parameter for
storage volumes:

-  Add the ``qos:IOThrottling`` key into a QOS specification and
   associate it with a volume type.

-  Add the ``qos:IOThrottling`` key into an extra specification with a
   volume type.

-  Add the ``qos:IOThrottling`` key to the storage volume metadata.

.. note::

   If you are changing a volume type with QOS to a new volume type
   without QOS, the QOS configuration settings will be removed.

Operational notes for the Storwize family and SVC driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Migrate volumes
---------------

In the context of OpenStack Block Storage's volume migration feature,
the IBM Storwize/SVC driver enables the storage's virtualization
technology. When migrating a volume from one pool to another, the volume
will appear in the destination pool almost immediately, while the
storage moves the data in the background.

.. note::

   To enable this feature, both pools involved in a given volume
   migration must have the same values for ``extent_size``. If the
   pools have different values for ``extent_size``, the data will still
   be moved directly between the pools (not host-side copy), but the
   operation will be synchronous.

Extend volumes
--------------

The IBM Storwize/SVC driver allows for extending a volume's size, but
only for volumes without snapshots.

Snapshots and clones
--------------------

Snapshots are implemented using FlashCopy with no background copy
(space-efficient). Volume clones (volumes created from existing volumes)
are implemented with FlashCopy, but with background copy enabled. This
means that volume clones are independent, full copies. While this
background copy is taking place, attempting to delete or extend the
source volume will result in that operation waiting for the copy to
complete.

Volume retype
-------------

The IBM Storwize/SVC driver enables you to modify volume types. When you
modify volume types, you can also change these extra specs properties:

-  rsize

-  warning

-  autoexpand

-  grainsize

-  compression

-  easytier

-  iogrp

-  nofmtdisk

-  mirror_pool

.. note::

   When you change the ``rsize``, ``grainsize`` or ``compression``
   properties, volume copies are asynchronously synchronized on the
   array.

.. note::

   To change the ``iogrp`` property, IBM Storwize/SVC firmware version
   6.4.0 or later is required.

Replication operation
---------------------

A volume is only replicated if the volume is created with a volume-type
that has the extra spec ``replication_enabled`` set to ``<is> True``. Three
types of replication are supported now, global mirror(async), global mirror
with change volume(async) and metro mirror(sync). It can be specified by a
volume-type that has the extra spec ``replication_type`` set to
``<in> global``, ``<in> gmcv`` or ``<in> metro``. If no ``replication_type``
is specified, global mirror will be created for replication.

If ``replication_type`` set to ``<in> gmcv``, cycle_period_seconds can be
set as the cycling time perform global mirror relationship with multi cycling
mode. Default value is 300. Example syntax:

.. code-block:: console

   $ cinder type-create gmcv_type
   $ cinder type-key gmcv_type set replication_enabled='<is> True' \
     replication_type="<in> gmcv" drivers:cycle_period_seconds=500

.. note::

   It is better to establish the partnership relationship between
   the replication source storage and the replication target
   storage manually on the storage back end before replication
   volume creation.

The ``failover-host`` command is designed for the case where the primary
storage is down.

.. code-block:: console

   $ cinder failover-host cinder@svciscsi --backend_id target_svc_id

If a failover command has been executed and the primary storage has
been restored, it is possible to do a failback by simply specifying
default as the ``backend_id``:

.. code-block:: console

   $ cinder failover-host cinder@svciscsi --backend_id default

.. note::

   Before you perform a failback operation, synchronize the data
   from the replication target volume to the primary one on the
   storage back end manually, and do the failback only after the
   synchronization is done since the synchronization may take a long time.
   If the synchronization is not done manually, Storwize Block Storage
   service driver will perform the synchronization and do the failback
   after the synchronization is finished.
