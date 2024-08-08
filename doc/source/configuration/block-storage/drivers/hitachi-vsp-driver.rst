============================
Hitachi block storage driver
============================

Hitachi block storage driver provides Fibre Channel and iSCSI support for
Hitachi VSP storages.

System requirements
~~~~~~~~~~~~~~~~~~~

Supported storages:

+-----------------+------------------------+
| Storage model   | Firmware version       |
+=================+========================+
| VSP E590,       | 93-03-22 or later      |
| E790            |                        |
+-----------------+------------------------+
| VSP E990        | 93-01-01 or later      |
+-----------------+------------------------+
| VSP E1090,      | 93-06-2x or later      |
| E1090H          |                        |
+-----------------+------------------------+
| VSP F350,       | 88-01-04 or later      |
| F370,           |                        |
| F700,           |                        |
| F900            |                        |
|                 |                        |
| VSP G350,       |                        |
| G370,           |                        |
| G700,           |                        |
| G900            |                        |
+-----------------+------------------------+
| VSP F400,       | 83-04-43 or later      |
| F600,           |                        |
| F800            |                        |
|                 |                        |
| VSP G200,       |                        |
| G400,           |                        |
| G600,           |                        |
| G800            |                        |
+-----------------+------------------------+
| VSP N400,       | 83-06-01 or later      |
| N600,           |                        |
| N800            |                        |
+-----------------+------------------------+
| VSP 5100,       | 90-01-41 or later      |
| 5500,           |                        |
| 5100H,          |                        |
| 5500H           |                        |
+-----------------+------------------------+
| VSP 5200,       | 90-08-0x or later      |
| 5600,           |                        |
| 5200H,          |                        |
| 5600H           |                        |
+-----------------+------------------------+
| VSP F1500       | 80-05-43 or later      |
|                 |                        |
| VSP G1000,      |                        |
| VSP G1500       |                        |
+-----------------+------------------------+

Required storage licenses:

* Hitachi Storage Virtualization Operating System (SVOS)

  - Hitachi LUN Manager
  - Hitachi Dynamic Provisioning
* Hitachi Local Replication (Hitachi Thin Image)

Optional storage licenses:

* Deduplication and compression

* Global-Active Device

Supported operations
~~~~~~~~~~~~~~~~~~~~

* Create, delete, attach, and detach volumes.
* Create, list, and delete volume snapshots.
* Create a volume from a snapshot.
* Create, list, update, and delete consistency groups.
* Create, list, and delete consistency group snapshots.
* Copy a volume to an image.
* Copy an image to a volume.
* Clone a volume.
* Extend a volume.
* Migrate a volume (host assisted).
* Migrate a volume (storage assisted).
* Get volume statistics.
* Efficient non-disruptive volume backup.
* Manage and unmanage a volume.
* Attach a volume to multiple instances at once (multi-attach).
* Revert a volume to a snapshot.

Hitachi block storage driver also supports the following additional features:

* Global-Active Device
* Maximum number of copy pairs and consistency groups
* Data deduplication and compression
* Port scheduler
* Port assignment using extra spec

.. note::

   * A volume having snapshots cannot be extended with this driver.

   * Storage assisted volume migration is only supported between same storage.

Configuration
~~~~~~~~~~~~~

Set up Hitachi storage
----------------------

You need to specify settings as described below for storage systems. For
details about each setting, see the user's guide of the storage systems.

Common resources:

1. ``All resources``
    The name of any storage resource, such as a DP pool or a host group,
    cannot contain any whitespace characters or else it will be unusable
    by the driver.

2. ``User accounts``
    Create a storage device account belonging to the Administrator User Group.

3. ``DP Pool``
    Create a DP pool that is used by the driver.

4. ``Resource group``
    If using a new resource group for exclusive use by an OpenStack system,
    create a new resource group, and assign the necessary resources, such as
    LDEVs, port, and host group (iSCSI target) to the created resource.

5. ``Ports``
    Enable Port Security for the ports used by the driver.

If you use iSCSI:

1. ``Ports``
    Assign an IP address and a TCP port number to the port.

.. note::

   * Do not change LDEV nickname for the LDEVs created by Hitachi block
     storage driver. The nickname is referred when deleting a volume or
     a snapshot, to avoid data-loss risk. See details in `bug #2072317`_.

Set up Hitachi storage volume driver and volume operations
----------------------------------------------------------

Set the volume driver to Hitachi block storage driver by setting the
volume_driver option in the cinder.conf file as follows:

If you use Fibre Channel:

.. code-block:: ini

   [hitachi_vsp]
   volume_driver = cinder.volume.drivers.hitachi.hbsd_fc.HBSDFCDriver
   volume_backend_name = hitachi_vsp
   san_ip = 1.2.3.4
   san_login = hitachiuser
   san_password = password
   hitachi_storage_id = 123456789012
   hitachi_pools = pool0

If you use iSCSI:

.. code-block:: ini

   [hitachi_vsp]
   volume_driver = cinder.volume.drivers.hitachi.hbsd_iscsi.HBSDISCSIDriver
   volume_backend_name = hitachi_vsp
   san_ip = 1.2.3.4
   san_login = hitachiuser
   san_password = password
   hitachi_storage_id = 123456789012
   hitachi_pools = pool0, pool1

Configuration options
~~~~~~~~~~~~~~~~~~~~~

This table shows configuration options for Hitachi block storage driver.

.. config-table::
   :config-target: Hitachi block storage driver

   cinder.volume.drivers.hitachi.hbsd_common
   cinder.volume.drivers.hitachi.hbsd_rest
   cinder.volume.drivers.hitachi.hbsd_rest_fc
   cinder.volume.drivers.hitachi.hbsd_replication

Required options
----------------

- ``san_ip``
    IP address of SAN controller

- ``san_login``
    Username for SAN controller

- ``san_password``
    Password for SAN controller

- ``hitachi_storage_id``
    Product number of the storage system.

- ``hitachi_pools``
    Pool number(s) or pool name(s) of the DP pool.

Set up and operation for additional features
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Set up Global-Active Device and volume operation
------------------------------------------------

Beginning with the 2023.1, If you use Global-Active Device (GAD),
you can make the data of individual volumes redundant between two
storage systems, thereby improving the availability of the storage systems.
For details, see the `Global-Active Device User Guide`_.

.. note::

   * You cannot apply Global-Active Device configuration and remote
     replication configuration to the same backend.

   * You cannot use Asymmetric Logical Unit Access (ALUA).

Storage firmware versions for GAD
<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

If you are using a VSP F350, F370, F700, F900 storage system or a VSP G350,
G370, G700,G900 storage system in a Global-Active Device configuration,
make sure the firmware version is 88-03-21 or later.

Creating a Global-Active Device environment
<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

Before using Global-Active Device, create the prerequisite environment,
such as connecting remote paths, configuring a quorum disk,
and creating a virtual storage machine (VSM), by other storage system
management tools. Hitachi block storage driver supports the following
configurations.

* Configuration where the P-VOL is not registered to a VSM

* Configuration where the P-VOL is registered to a VSM

For details, see the Workflow for creating a GAD environment in the
`Global-Active Device User Guide`_

Hitachi block storage driver automatically setups following procedures
that are described in the section `Workflow for creating a GAD environment`_ :

* The following steps of Setting up the secondary storage system:

  - Setting the GAD reserve attribute on the S-VOL
  - Creating a host group (Only if the configuration option
    ``hitachi_group_create`` is True)
  - Creating the S-VOL
  - Adding an LU path to the S-VOL

* Updating the CCI configuration definition files

* Creating the GAD pair

* Adding an alternate path to the S-VOL

You must register the information about the secondary storage system to the
REST API server in the primary site and register the information about the
primary storage system to the REST API server in the secondary site.
For details about how to register the information, see the
`Hitachi Command Suite Configuration Manager REST API Reference Guide`_ or
the `Hitachi Ops Center API Configuration Manager REST API Reference Guide`_.

.. note::

   * The users specified for both configuration options
     ``san_login`` and ``hitachi_mirror_rest_user`` must have following
     roles:

     * Storage Administrator (View & Modify)

     * Storage Administrator (Remote Copy)

   * Reserve unused host group IDs (iSCSI target IDs) for the resource groups
     related on the VSM. Reserve the IDs in ascending order. The number of IDs
     you need to reserve is 1 plus the sum of the number of controller nodes
     and the number of compute nodes. For details on how to reserve a host
     group ID (iSCSI target ID), see `Global-Active Device User Guide`_.
   * The LUNs of the host groups (iSCSI targets) of the specified ports on
     the primary storage system must match the LUNs of the host groups
     (iSCSI targets) of the specified ports on the secondary storage system.
     If they do not match, match the LUNs for the primary storage system with
     those for the secondary storage system.
   * When you use a same storage system as secondary storage system for
     Global-Active Device configuration and backend storage system for general
     use at the same time, you cannot use the same ports between different
     backend storage systems.
     Please specify different ports in the configuration options
     ``hitachi_target_ports``, ``hitachi_compute_target_ports``, or
     ``hitachi_rest_pair_target_ports`` between different backend storage
     systems.

Create volume in a Global-Active Device configuration
<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

If you create a Cinder volume in a Global-Active Device configuration,
each Global-Active Device pair is mapped to a Cinder volume.

In order for you to create volumes with the Global-Active Device attribute
specified, you must first create a volume type that contains the
``hbsd:topology=active_active_mirror_volume`` extra-spec.
You can do this as follows:

.. code-block:: console

   $ openstack volume type create <volume type name>
   $ openstack volume type set --property \
   hbsd:topology=active_active_mirror_volume <volume type name>

You can then create GAD volumes as follows:

.. code-block:: console

   $ openstack volume create --type <volume type name> --size <size>

.. note::

   * In this case, the following restrictions apply:

     * You cannot create a volume for which the deduplication and compression
       function is enabled, or creating a volume will be failed with the error
       ``MSGID0753-E: Failed to create a volume in a GAD environment because
       deduplication is enabled for the volume type.``.

   * Note the following if the configuration is "P-VOL registered to a VSM":

     * Do not create volumes whose volume types do not have
       ``hbsd:topology=active_active_mirror_volume`` extra-spec.

     * While setting up the environment, set a virtual LDEV ID for every LDEV
       specified by the configuration option ``hitachi_ldev_range parameter``
       on the primary storage system using storage management software
       because virtual LDEV IDs are necessary for GAD pair creation.

Unavailable Cinder functions
<<<<<<<<<<<<<<<<<<<<<<<<<<<<

Following cinder functions are unavailable in a Global-Active Device
configuration:

* Migrate a volume (storage assisted)

* Manage Volume

* Unmanage Volume

.. note::

   In addition, if the configuration is "P-VOL registered to a VSM",
   the backup creation command of the Backup Volume functions cannot be run
   with the ``--snapshot option`` or the ``--force`` option specified.

Maximum number of copy pairs and consistency groups
---------------------------------------------------

The maximum number of Thin Image pairs that can be created for each LDEV
assigned to a volume (or snapshot) is restricted on a per-storage-system basis.
If the number of pairs exceeds the maximum, copying cannot proceed normally.

For information about the maximum number of copy pairs and consistency groups
that can be created, see the `Hitachi Thin Image User Guide`_.

Data deduplication and compression
----------------------------------

Use deduplication and compression to improve storage utilization using data
reduction.

For details,
see `Capacity saving function: data deduplication and compression`_
in the `Provisioning Guide`_.

**Enabling deduplication and compression**

To use the deduplication and compression on the storage models, your storage
administrator must first enable the deduplication and compression for the DP
pool.

For details about how to enable this setting, see the description of pool
management in the
`Hitachi Command Suite Configuration Manager REST API Reference Guide`_ or the
`Hitachi Ops Center API Configuration Manager REST API Reference Guide`_.

.. note::

   * Do not set a subscription limit (virtualVolumeCapacityRate) for the DP
     pool.

Creating a volume with deduplication and compression enabled
<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

To create a volume with the deduplication and compression setting enabled,
enable deduplication and compression for the relevant volume type.

**Procedure**

1. To enable the deduplication and compression setting, specify the value
``deduplication_compression`` for ``hbsd:capacity_saving`` in the extra specs
for the volume type.

2. When creating a volume of the volume type created in the previous step,
you can create a volume with the deduplication and compression function
enabled.

Deleting a volume with deduplication and compression enabled
<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

The cinder delete command finishes when the storage system starts the LDEV
deletion process. The LDEV cannot be reused until the LDEV deletion process is
completed on the storage system.

Port scheduler
--------------

You can use the port scheduler function to reduce the number of WWNs,
which are storage system resource.

In Hitachi block storage driver, if host groups are created automatically,
host groups are created for each compute node or VM (in an environment that
has a WWN for each VM). If you do not use the port scheduler function,
host groups are created and the same WWNs are registered in all of the ports
that are specified for the configuration option
``hitachi_compute_target_ports`` or for the configuration option
``hitachi_target_ports``.
For Hitachi storage devices, a maximum of 255 host groups and 255 WWNs can be
registered for one port.
When volumes are attached, the upper limit on the number of WWNs that can be
registered might be unexpectedly exceeded.

For the port scheduler function, when the cinder-volume service starts,
the Fibre Channel Zone Manager obtains the WWNs of active compute nodes and
of active VMs. When volumes are attached, the WWNs are registered in
a round-robin procedure, in the same order as the order of ports specified
for the configuiration option ``hitachi_compute_target_ports`` or for the
configuiration option ``hitachi_target_ports``.

If you want to use the port scheduler function,
set the configuration option ``hitachi_port_scheduler``.

.. note::

   * Only Fibre Channel is supported. For details about ports,
     see Fibre Channel connectivity.
   * If a host group already exists in any of the ports specified for the
     configuration option ``hitachi_compute_target_ports`` or for the
     configuration option ``hitachi_target_ports``, no new host group will be
     created on those ports.
   * Restarting the cinder-volume service re-initializes the round robin
     scheduling determined by the configuration option
     ``hitachi_compute_target_ports`` or the configuration option
     ``hitachi_target_ports``.
   * The port scheduler function divides up the active WWNs from each fabric
     controller and registers them to each port. For this reason,
     the number of WWNs registered may vary from port to port.

Port assignment using extra specs
---------------------------------

Defining particular ports in the Hitachi-supported extra spec
``hbsd:target_ports`` determines which of the ports specified by the
configuration options ``hitachi_target_ports`` or the configuration option
``hitachi_compute_target_ports`` are used to create LUN paths during volume
attach operations for each volume type.

.. note::

   * Use a comma to separate multiple ports.
   * In a Global-Active Device configuration, use the extra spec
     ``hbsd:target_ports`` for the primary storage system and the extra spec
     ``hbsd:remote_target_ports`` for the secondary storage system.
   * In a Global-Active Device configuration, the ports specified for
     the extra spec ``hbsd:target_ports`` must be specified for both the
     configuration options for the primary storage system
     (``hitachi_target_ports`` or ``hitachi_compute_target_ports``)
     and for the secondary storage system
     (``hitachi_mirror_target_ports`` or
     ``hitachi_mirror_compute_target_ports``).

.. Document Hyperlinks
.. _Global-Active Device User Guide: https://knowledge.hitachivantara.com/
  Documents/Management_Software/SVOS/9.8.7/Global-Active_Device
.. _Hitachi Command Suite Configuration Manager REST API Reference Guide:
  https://knowledge.hitachivantara.com/Documents/Management_Software/
  Ops_Center/API_Configuration_Manager/10.5.x/REST_API_Reference_Guide
.. _Hitachi Ops Center API Configuration Manager REST API Reference Guide:
  https://knowledge.hitachivantara.com/Documents/Management_Software/
  Ops_Center/10.9.x/API_Configuration_Manager
.. _Hitachi Thin Image User Guide: https://knowledge.hitachivantara.com/
  Documents/Management_Software/SVOS/7.3.1/Administration_Guides/
  Thin_Image_User_Guide
.. _Workflow for creating a GAD environment:
  https://knowledge.hitachivantara.com/Documents/Management_Software/SVOS/
  9.8.7/Global-Active_Device/04_Configuration_and_pair_management_using_CCI
.. _Provisioning Guide:
  https://docs.hitachivantara.com/r/en-us/svos/9.8.7/mk-97hm85026/
  introduction-to-provisioning
.. _Capacity saving function\: data deduplication and compression:
  https://docs.hitachivantara.com/r/en-us/svos/9.8.7/mk-97hm85026/
  about-adaptive-data-reduction/capacity-saving/
  capacity-saving-function-data-deduplication-and-compression
.. _bug #2072317:
  https://bugs.launchpad.net/cinder/+bug/2072317
