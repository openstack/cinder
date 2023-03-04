============================
HPE XP block storage driver
============================

HPE XP block storage driver provides Fibre Channel and iSCSI support for
HPE XP storages.

System requirements
~~~~~~~~~~~~~~~~~~~

Supported storages:

+-----------------+------------------------+
| Storage model   | Firmware version       |
+=================+========================+
| XP8             | 90-01-41 or later      |
+-----------------+------------------------+
| XP7             | 80-05-43 or later      |
+-----------------+------------------------+

Required storage licenses:

* Thin Provisioning
* Fast Snap

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

Set up HPE XP storage
----------------------

You need to specify settings as described below for storage systems. For
details about each setting, see the user's guide of the storage systems.

#. User accounts

   Create a storage device account belonging to the Administrator User Group.

#. THP pool

   Create a THP pool that is used by the driver.

#. Ports

   Enable Port Security for the ports used by the driver.

Set up HPE XP storage volume driver
------------------------------------

Set the volume driver to HPE XP block storage driver by setting the
volume_driver option in the cinder.conf file as follows:

If you use Fibre Channel:

.. code-block:: ini

   [hpe_xp]
   volume_driver = cinder.volume.drivers.hpe.xp.hpe_xp_fc.HPEXPFCDriver
   volume_backend_name = hpexp_fc
   san_ip = 1.2.3.4
   san_login = hpexpuser
   san_password = password
   hpexp_storage_id = 123456789012
   hpexp_pools = pool0

If you use iSCSI:

.. code-block:: ini

   [hpe_xp]
   volume_driver = cinder.volume.drivers.hpe.xp.hpe_xp_iscsi.HPEXPISCSIDriver
   volume_backend_name = hpexp_iscsi
   san_ip = 1.2.3.4
   san_login = hpexpuser
   san_password = password
   hpexp_storage_id = 123456789012
   hpexp_pools = pool0

This table shows configuration options for HPE XP block storage driver.

.. config-table::
   :config-target: HPE XP block storage driver

   cinder.volume.drivers.hpe.xp.hpe_xp_rest

Required options
----------------

- ``san_ip``
    IP address of SAN controller

- ``san_login``
    Username for SAN controller

- ``san_password``
    Password for SAN controller

- ``hpexp_storage_id``
    Product number of the storage system.

- ``hpexp_pools``
    Pool number(s) or pool name(s) of the THP pool.

