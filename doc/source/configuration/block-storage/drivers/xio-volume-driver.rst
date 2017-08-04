==================
X-IO volume driver
==================

The X-IO volume driver for OpenStack Block Storage enables ISE products to be
managed by OpenStack Block Storage nodes. This driver can be configured to work
with iSCSI and Fibre Channel storage protocols. The X-IO volume driver allows
the cloud operator to take advantage of ISE features like quality of
service (QoS) and Continuous Adaptive Data Placement (CADP). It also supports
creating thin volumes and specifying volume media affinity.

Requirements
~~~~~~~~~~~~

ISE FW 2.8.0 or ISE FW 3.1.0 is required for OpenStack Block Storage
support. The X-IO volume driver will not work with older ISE FW.

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, delete, attach, detach, retype, clone, and extend volumes.
- Create a volume from snapshot.
- Create, list, and delete volume snapshots.
- Manage and unmanage a volume.
- Get volume statistics.
- Create a thin provisioned volume.
- Create volumes with QoS specifications.

Configure X-IO Volume driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To configure the use of an ISE product with OpenStack Block Storage, modify
your ``cinder.conf`` file as follows. Be careful to use the one that matches
the storage protocol in use:

Fibre Channel
-------------

.. code-block:: ini

   volume_driver = cinder.volume.drivers.xio.XIOISEFCDriver
   san_ip = 1.2.3.4              # the address of your ISE REST management interface
   san_login = administrator     # your ISE management admin login
   san_password = password       # your ISE management admin password

iSCSI
-----

.. code-block:: ini

   volume_driver = cinder.volume.drivers.xio.XIOISEISCSIDriver
   san_ip = 1.2.3.4              # the address of your ISE REST management interface
   san_login = administrator     # your ISE management admin login
   san_password = password       # your ISE management admin password
   iscsi_ip_address = ionet_ip   # ip address to one ISE port connected to the IONET

Optional configuration parameters
---------------------------------

.. include:: ../../tables/cinder-xio.inc

Multipath
---------

The X-IO ISE supports a multipath configuration, but multipath must be enabled
on the compute node (see *ISE Storage Blade Best Practices Guide*).
For more information, see `X-IO Document Library
<http://xiostorage.com/document_library/>`__.

Volume types
------------

OpenStack Block Storage uses volume types to help the administrator specify
attributes for volumes. These attributes are called extra-specs.  The X-IO
volume driver support the following extra-specs.

.. list-table:: Extra specs
   :header-rows: 1

   * - Extra-specs name
     - Valid values
     - Description
   * - ``Feature:Raid``
     - 1, 5
     - RAID level for volume.
   * - ``Feature:Pool``
     - 1 - n (n being number of pools on ISE)
     - Pool to create volume in.
   * - ``Affinity:Type``
     - cadp, flash, hdd
     - Volume media affinity type.
   * - ``Alloc:Type``
     - 0 (thick), 1 (thin)
     - Allocation type for volume. Thick or thin.
   * - ``QoS:minIOPS``
     - n (value less than maxIOPS)
     - Minimum IOPS setting for volume.
   * - ``QoS:maxIOPS``
     - n (value bigger than minIOPS)
     - Maximum IOPS setting for volume.
   * - ``QoS:burstIOPS``
     - n (value bigger than minIOPS)
     - Burst IOPS setting for volume.

Examples
--------

Create a volume type called xio1-flash for volumes that should reside on ssd
storage:

.. code-block:: console

   $ openstack volume type create xio1-flash
   $ openstack volume type set --property Affinity:Type=flash xio1-flash

Create a volume type called xio1 and set QoS min and max:

.. code-block:: console

   $ openstack volume type create xio1
   $ openstack volume type set --property QoS:minIOPS=20 xio1
   $ openstack volume type set --property QoS:maxIOPS=5000 xio1
