=============================
IBM FlashSystem volume driver
=============================

The volume driver for FlashSystem provides OpenStack Block Storage hosts
with access to IBM FlashSystems.

Supported operations
~~~~~~~~~~~~~~~~~~~~

These operations are supported:

-  Create, delete, attach, and detach volumes.

-  Create, list, and delete volume snapshots.

-  Create a volume from a snapshot.

-  Copy an image to a volume.

-  Copy a volume to an image.

-  Clone a volume.

-  Extend a volume.

-  Get volume statistics.

-  Manage and unmanage a volume.

Configure FlashSystem
~~~~~~~~~~~~~~~~~~~~~

Configure storage array
-----------------------

The volume driver requires a pre-defined array. You must create an
array on the FlashSystem before using the volume driver. An existing array
can also be used and existing data will not be deleted.

.. note::

   FlashSystem can only create one array, so no configuration option is
   needed for the IBM FlashSystem driver to assign it.

Configure user authentication for the driver
--------------------------------------------

The driver requires access to the FlashSystem management interface using
SSH. It should be provided with the FlashSystem management IP using the
``san_ip`` flag, and the management port should be provided by the
``san_ssh_port`` flag. By default, the port value is configured to be
port 22 (SSH).

.. note::

   Make sure the compute node running the ``cinder-volume`` driver has SSH
   network access to the storage system.

Using password authentication, assign a password to the user on the
FlashSystem. For more detail, see the driver configuration flags
for the user and password here: :ref:`config_fc_flags`
or :ref:`config_iscsi_flags`.

There are some common configuration options for either driver:

.. list-table:: List of common configuration options for IBM FlashSystem drivers
   :header-rows: 1

   * - Flag name
     - Type
     - Default
     - Description
   * - ``san_ip``
     - Required
     -
     - Management IP or host name
   * - ``san_ssh_port``
     - Optional
     - 22
     - Management port
   * - ``san_login``
     - Required
     -
     - Management login user name
   * - ``san_password``
     - Required
     -
     - Management login password

IBM FlashSystem FC driver
~~~~~~~~~~~~~~~~~~~~~~~~~

Data Path configuration
-----------------------

Using Fiber Channel (FC), each FlashSystem node should have at least one
WWPN port configured. If the ``flashsystem_multipath_enabled`` flag is
set to ``True`` in the Block Storage service configuration file, the driver
uses all available WWPNs to attach the volume to the instance. If the flag is
not set, the driver uses the WWPN associated with the volume's preferred node
(if available). Otherwise, it uses the first available WWPN of the system. The
driver obtains the WWPNs directly from the storage system. You do not need to
provide these WWPNs to the driver.

.. note::

   Using FC, ensure that the block storage hosts have FC connectivity
   to the FlashSystem.

.. _config_fc_flags:

Enable IBM FlashSystem FC driver
--------------------------------

Set the volume driver to the FlashSystem driver by setting the
``volume_driver`` option in the ``cinder.conf`` configuration file,
as follows:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.ibm.flashsystem_fc.FlashSystemFCDriver

To enable the IBM FlashSystem FC driver, configure the following options in the
``cinder.conf`` configuration file:

.. config-table::
   :config-target: IBM FlashSystem FC

   cinder.volume.drivers.ibm.flashsystem_common
   cinder.volume.drivers.ibm.flashsystem_fc

IBM FlashSystem iSCSI driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Network configuration
---------------------

Using iSCSI, each FlashSystem node should have at least one iSCSI port
configured. iSCSI IP addresses of IBM FlashSystem can be obtained by
FlashSystem GUI or CLI. For more information, see the
appropriate IBM Redbook for the FlashSystem.

.. note::

   Using iSCSI, ensure that the compute nodes have iSCSI network access
   to the IBM FlashSystem.

.. _config_iscsi_flags:

Enable IBM FlashSystem iSCSI driver
-----------------------------------

Set the volume driver to the FlashSystem driver by setting the
``volume_driver`` option in the ``cinder.conf`` configuration file, as
follows:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.ibm.flashsystem_iscsi.FlashSystemISCSIDriver

To enable IBM FlashSystem iSCSI driver, configure the following options
in the ``cinder.conf`` configuration file:

.. config-table::
   :config-target: IBM FlashSystem iSCSI

   cinder.volume.drivers.ibm.flashsystem_common
   cinder.volume.drivers.ibm.flashsystem_iscsi

.. note::

   On the cluster of the FlashSystem, the ``iscsi_ip_address`` column is the
   seventh column ``IP_address`` of the output of ``lsportip``.

.. note::

   On the cluster of the FlashSystem, port ID column is the first
   column ``id`` of the output of ``lsportip``,
   not the sixth column ``port_id``.

Limitations and known issues
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

IBM FlashSystem only works when:

.. code-block:: ini

   open_access_enabled=off

.. note::

    The ``flashsystem_multihost_enabled`` setting allows the driver to map a
    vdisk to more than one host at a time. This scenario occurs during
    migration of a virtual machine with an attached volume; the volume is
    simultaneously mapped to both the source and destination compute hosts. If
    your deployment does not require attaching vdisks to multiple hosts,
    setting this flag to ``False`` will provide added safety.
