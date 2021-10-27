===========================
NEC Storage V series driver
===========================

NEC Storage V series driver provides Fibre Channel and iSCSI support for
NEC V series storages.

System requirements
~~~~~~~~~~~~~~~~~~~
Supported models:

+-----------------+------------------------+
| Storage model   | Firmware version       |
+=================+========================+
| V100,           | 93-04-21 or later      |
| V300            |                        |
+-----------------+------------------------+

Required storage licenses:

* iStorage Local Replication
  Local Replication Software


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

   A volume with snapshots cannot be extended in this driver.

Configuration
~~~~~~~~~~~~~
Set up NEC V series storage
---------------------------

You need to specify settings as described below for storage systems. For
details about each setting, see the user's guide of the storage systems.

Common resources:

- ``All resources``
    All storage resources, such as DP pools and host groups, can not have a
    name including blank space in order for the driver to use them.

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

Set up NEC V series storage volume driver
-----------------------------------------

Set the volume driver to NEC V series storage driver by setting the
volume_driver option in the cinder.conf file as follows:

If you use Fibre Channel:

.. code-block:: ini

   [Storage1]
   volume_driver = cinder.volume.drivers.nec.v.nec_v_fc.VStorageFCDriver
   volume_backend_name = Storage1
   san_ip = 1.2.3.4
   san_api_port = 23451
   san_login = userid
   san_password = password
   nec_v_storage_id = 123456789012
   nec_v_pool = pool0

If you use iSCSI:

.. code-block:: ini

   [Storage1]
   volume_driver = cinder.volume.drivers.nec.v.nec_v_iscsi.VStorageISCSIDriver
   volume_backend_name = Storage1
   san_ip = 1.2.3.4
   san_api_port = 23451
   san_login = userid
   san_password = password
   nec_v_storage_id = 123456789012
   nec_v_pool = pool0

This table shows configuration options for NEC V series storage driver.

.. config-table::
   :config-target: NEC V series storage driver

   cinder.volume.drivers.nec.v.nec_v_rest

Required options
----------------

- ``san_ip``
    IP address of SAN controller

- ``san_login``
    Username for SAN controller

- ``san_password``
    Password for SAN controller

- ``nec_v_storage_id``
    Product number of the storage system.

- ``nec_v_pool``
    Pool number or pool name of the DP pool.

