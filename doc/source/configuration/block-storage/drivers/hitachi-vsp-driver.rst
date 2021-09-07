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
| VSP E990,       | 93-01-01 or later      |
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

#. User accounts

   Create a storage device account belonging to the Administrator User Group.

#. DP Pool

   Create a DP pool that is used by the driver.

#. Ports

   Enable Port Security for the ports used by the driver.

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
   hitachi_pool = pool0

If you use iSCSI:

.. code-block:: ini

   [hitachi_vsp]
   volume_driver = cinder.volume.drivers.hitachi.hbsd_iscsi.HBSDISCSIDriver
   volume_backend_name = hitachi_vsp
   san_ip = 1.2.3.4
   san_login = hitachiuser
   san_password = password
   hitachi_storage_id = 123456789012
   hitachi_pool = pool0

This table shows configuration options for Hitachi block storage driver.

.. config-table::
   :config-target: Hitachi block storage driver

   cinder.volume.drivers.hitachi.hbsd_common
   cinder.volume.drivers.hitachi.hbsd_rest
   cinder.volume.drivers.hitachi.hbsd_fc

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

- ``hitachi_pool``
    Pool number or pool name of the DP pool.

