=============================
Hitachi storage volume driver
=============================

Hitachi storage volume driver provides iSCSI and Fibre Channel
support for Hitachi storages.

System requirements
~~~~~~~~~~~~~~~~~~~

Supported storages:

* Hitachi Virtual Storage Platform G1000 (VSP G1000)
* Hitachi Virtual Storage Platform (VSP)
* Hitachi Unified Storage VM (HUS VM)
* Hitachi Unified Storage 100 Family (HUS 100 Family)

Required software:

* RAID Manager Ver 01-32-03/01 or later for VSP G1000/VSP/HUS VM
* Hitachi Storage Navigator Modular 2 (HSNM2) Ver 27.50 or later
  for HUS 100 Family

  .. note::

     HSNM2 needs to be installed under ``/usr/stonavm``.

Required licenses:

* Hitachi In-System Replication Software for VSP G1000/VSP/HUS VM
* (Mandatory) ShadowImage in-system replication for HUS 100 Family
* (Optional) Copy-on-Write Snapshot for HUS 100 Family

Additionally, the ``pexpect`` package is required.

Supported operations
~~~~~~~~~~~~~~~~~~~~

* Create, delete, attach, and detach volumes.
* Create, list, and delete volume snapshots.
* Manage and unmanage volume snapshots.
* Create a volume from a snapshot.
* Copy a volume to an image.
* Copy an image to a volume.
* Clone a volume.
* Extend a volume.
* Get volume statistics.

Configuration
~~~~~~~~~~~~~

Set up Hitachi storage
----------------------

You need to specify settings as described below. For details about each step,
see the user's guide of the storage device. Use a storage administrative
software such as ``Storage Navigator`` to set up the storage device so that
LDEVs and host groups can be created and deleted, and LDEVs can be connected
to the server and can be asynchronously copied.

#. Create a Dynamic Provisioning pool.

#. Connect the ports at the storage to the controller node and compute nodes.

#. For VSP G1000/VSP/HUS VM, set ``port security`` to ``enable`` for the
   ports at the storage.

#. For HUS 100 Family, set ``Host Group security`` or
   ``iSCSI target security`` to ``ON`` for the ports at the storage.

#. For the ports at the storage, create host groups (iSCSI targets) whose
   names begin with HBSD- for the controller node and each compute node.
   Then register a WWN (initiator IQN) for each of the controller node and
   compute nodes.

#. For VSP G1000/VSP/HUS VM, perform the following:

   * Create a storage device account belonging to the Administrator User
     Group. (To use multiple storage devices, create the same account name
     for all the target storage devices, and specify the same resource
     group and permissions.)
   * Create a command device (In-Band), and set user authentication to ``ON``.
   * Register the created command device to the host group for the controller
     node.
   * To use the Thin Image function, create a pool for Thin Image.

#. For HUS 100 Family, perform the following:

   * Use the :command:`auunitaddauto` command to register the
     unit name and controller of the storage device to HSNM2.
   * When connecting via iSCSI, if you are using CHAP certification, specify
     the same user and password as that used for the storage port.

Set up Hitachi Gigabit Fibre Channel adaptor
--------------------------------------------

Change a parameter of the hfcldd driver and update the ``initram`` file
if Hitachi Gigabit Fibre Channel adaptor is used:

.. code-block:: console

   # /opt/hitachi/drivers/hba/hfcmgr -E hfc_rport_lu_scan 1
   # dracut -f initramfs-KERNEL_VERSION.img KERNEL_VERSION
   # reboot

Set up Hitachi storage volume driver
------------------------------------

#. Create a directory:

   .. code-block:: console

      # mkdir /var/lock/hbsd
      # chown cinder:cinder /var/lock/hbsd

#. Create ``volume type`` and ``volume key``.

   This example shows that HUS100_SAMPLE is created as ``volume type``
   and hus100_backend is registered as ``volume key``:

   .. code-block:: console

      $ openstack volume type create HUS100_SAMPLE
      $ openstack volume type set --property volume_backend_name=hus100_backend HUS100_SAMPLE

#. Specify any identical ``volume type`` name and ``volume key``.

   To confirm the created ``volume type``, please execute the following
   command:

   .. code-block:: console

      $ openstack volume type list --long

#. Edit the ``/etc/cinder/cinder.conf`` file as follows.

   If you use Fibre Channel:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.hitachi.hbsd_fc.HBSDFCDriver

   If you use iSCSI:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.hitachi.hbsd_iscsi.HBSDISCSIDriver

   Also, set ``volume_backend_name`` created by :command:`openstack volume type set`
   command:

   .. code-block:: ini

      volume_backend_name = hus100_backend

   This table shows configuration options for Hitachi storage volume driver.

   .. include:: ../../tables/cinder-hitachi-hbsd.inc

#. Restart the Block Storage service.

   When the startup is done, "MSGID0003-I: The storage backend can be used."
   is output into ``/var/log/cinder/volume.log`` as follows:

   .. code-block:: console

      2014-09-01 10:34:14.169 28734 WARNING cinder.volume.drivers.hitachi.
      hbsd_common [req-a0bb70b5-7c3f-422a-a29e-6a55d6508135 None None]
      MSGID0003-I: The storage backend can be used. (config_group: hus100_backend)
