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
* Migrate a volume.
* Get volume statistics.
* Efficient non-disruptive volume backup.
* Manage and unmanage a volume.
* Attach a volume to multiple instances at once (multi-attach).
* Revert a volume to a snapshot.

.. note::

   The volume having snapshots cannot be extended in this driver.

Configuration
~~~~~~~~~~~~~

Set up Hitachi storage
----------------------

You need to specify settings as described below for storage systems. For
details about each setting, see the user's guide of the storage systems.

Common resources:

- ``All resources``
    The name of any storage resource, such as a DP pool or a host group,
    cannot contain any whitespace characters or else it will be unusable
    by the driver.

- ``User accounts``
    Create a storage device account belonging to the Administrator User Group.

- ``DP Pool``
    Create a DP pool that is used by the driver.

- ``Resource group``
    If using a new resource group for exclusive use by an OpenStack system,
    create a new resource group, and assign the necessary resources, such as
    LDEVs, port, and host group (iSCSI target) to the created resource.

- ``Ports``
    Enable Port Security for the ports used by the driver.

If you use iSCSI:

- ``Ports``
    Assign an IP address and a TCP port number to the port.

.. note::

   * Do not change LDEV nickname for the LDEVs created by Hitachi block
     storage driver. The nickname is referred when deleting a volume or
     a snapshot, to avoid data-loss risk. See details in `bug #2072317`_.

Set up Hitachi storage volume driver
------------------------------------

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
   hitachi_pools = pool0

This table shows configuration options for Hitachi block storage driver.

.. config-table::
   :config-target: Hitachi block storage driver

   cinder.volume.drivers.hitachi.hbsd_common
   cinder.volume.drivers.hitachi.hbsd_rest
   cinder.volume.drivers.hitachi.hbsd_rest_fc

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

.. Document Hyperlinks
.. _bug #2072317:
  https://bugs.launchpad.net/cinder/+bug/2072317
