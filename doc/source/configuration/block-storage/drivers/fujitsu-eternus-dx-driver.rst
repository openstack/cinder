=========================
Fujitsu ETERNUS DX driver
=========================

Fujitsu ETERNUS DX driver provides FC and iSCSI support for
ETERNUS DX S3 series.

The driver performs volume operations by communicating with
ETERNUS DX. It uses a CIM client in Python called PyWBEM
to perform CIM operations over HTTP.

You can specify RAID Group and Thin Provisioning Pool (TPP)
in ETERNUS DX as a storage pool.

System requirements
~~~~~~~~~~~~~~~~~~~

Supported storages:

* ETERNUS DX60 S3
* ETERNUS DX100 S3/DX200 S3
* ETERNUS DX500 S3/DX600 S3
* ETERNUS DX8700 S3/DX8900 S3
* ETERNUS DX200F

Requirements:

* Firmware version V10L30 or later is required.
* The multipath environment with ETERNUS Multipath Driver is unsupported.
* An Advanced Copy Feature license is required
  to create a snapshot and a clone.

Supported operations
~~~~~~~~~~~~~~~~~~~~

* Create, delete, attach, and detach volumes.
* Create, list, and delete volume snapshots.
* Create a volume from a snapshot.
* Copy an image to a volume.
* Copy a volume to an image.
* Clone a volume.
* Extend a volume. (\*1)
* Get volume statistics.

(\*1): It is executable only when you use TPP as a storage pool.

Preparation
~~~~~~~~~~~

Package installation
--------------------

Install the ``python-pywbem`` package for your distribution.

ETERNUS DX setup
----------------

Perform the following steps using ETERNUS Web GUI or ETERNUS CLI.

.. note::
   * These following operations require an account that has the ``Admin`` role.
   * For detailed operations, refer to ETERNUS Web GUI User's Guide or
     ETERNUS CLI User's Guide for ETERNUS DX S3 series.

#. Create an account for communication with cinder controller.

#. Enable the SMI-S of ETERNUS DX.

#. Register an Advanced Copy Feature license and configure copy table size.

#. Create a storage pool for volumes.

#. (Optional) If you want to create snapshots
   on a different storage pool for volumes,
   create a storage pool for snapshots.

#. Create Snap Data Pool Volume (SDPV) to enable Snap Data Pool (SDP) for
   ``create a snapshot``.

#. Configure storage ports used for OpenStack.

   - Set those storage ports to CA mode.
   - Enable the host-affinity settings of those storage ports.

     (ETERNUS CLI command for enabling host-affinity settings):

     .. code-block:: console

        CLI> set fc-parameters -host-affinity enable -port <CM#><CA#><Port#>
        CLI> set iscsi-parameters -host-affinity enable -port <CM#><CA#><Port#>

#. Ensure LAN connection between cinder controller and MNT port of ETERNUS DX
   and SAN connection between Compute nodes and CA ports of ETERNUS DX.

Configuration
~~~~~~~~~~~~~

#. Add the following entries to ``/etc/cinder/cinder.conf``:

   FC entries:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.fujitsu.eternus_dx_fc.FJDXFCDriver
      cinder_eternus_config_file = /etc/cinder/eternus_dx.xml

   iSCSI entries:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.fujitsu.eternus_dx_iscsi.FJDXISCSIDriver
      cinder_eternus_config_file = /etc/cinder/eternus_dx.xml

   If there is no description about ``cinder_eternus_config_file``,
   then the parameter is set to default value
   ``/etc/cinder/cinder_fujitsu_eternus_dx.xml``.

#. Create a driver configuration file.

   Create a driver configuration file in the file path specified
   as ``cinder_eternus_config_file`` in ``cinder.conf``,
   and add parameters to the file as below:

   FC configuration:

   .. code-block:: xml

       <?xml version='1.0' encoding='UTF-8'?>
       <FUJITSU>
       <EternusIP>0.0.0.0</EternusIP>
       <EternusPort>5988</EternusPort>
       <EternusUser>smisuser</EternusUser>
       <EternusPassword>smispassword</EternusPassword>
       <EternusPool>raid5_0001</EternusPool>
       <EternusSnapPool>raid5_0001</EternusSnapPool>
       </FUJITSU>

   iSCSI configuration:

   .. code-block:: xml

       <?xml version='1.0' encoding='UTF-8'?>
       <FUJITSU>
       <EternusIP>0.0.0.0</EternusIP>
       <EternusPort>5988</EternusPort>
       <EternusUser>smisuser</EternusUser>
       <EternusPassword>smispassword</EternusPassword>
       <EternusPool>raid5_0001</EternusPool>
       <EternusSnapPool>raid5_0001</EternusSnapPool>
       <EternusISCSIIP>1.1.1.1</EternusISCSIIP>
       <EternusISCSIIP>1.1.1.2</EternusISCSIIP>
       <EternusISCSIIP>1.1.1.3</EternusISCSIIP>
       <EternusISCSIIP>1.1.1.4</EternusISCSIIP>
       </FUJITSU>

   Where:

   ``EternusIP``
       IP address for the SMI-S connection of the ETRENUS DX.

       Enter the IP address of MNT port of the ETERNUS DX.

   ``EternusPort``
       Port number for the SMI-S connection port of the ETERNUS DX.

   ``EternusUser``
       User name for the SMI-S connection of the ETERNUS DX.

   ``EternusPassword``
       Password for the SMI-S connection of the ETERNUS DX.

   ``EternusPool``
       Storage pool name for volumes.

       Enter RAID Group name or TPP name in the ETERNUS DX.

   ``EternusSnapPool``
       Storage pool name for snapshots.

       Enter RAID Group name in the ETERNUS DX.

   ``EternusISCSIIP`` (Multiple setting allowed)
       iSCSI connection IP address of the ETERNUS DX.

   .. note::

      * For ``EternusSnapPool``, you can specify only RAID Group name
        and cannot specify TPP name.
      * You can specify the same RAID Group name for ``EternusPool`` and ``EternusSnapPool``
        if you create volumes and snapshots on a same storage pool.

Configuration example
~~~~~~~~~~~~~~~~~~~~~

#. Edit ``cinder.conf``:

   .. code-block:: ini

      [DEFAULT]
      enabled_backends = DXFC, DXISCSI

      [DXFC]
      volume_driver = cinder.volume.drivers.fujitsu.eternus_dx_fc.FJDXFCDriver
      cinder_eternus_config_file = /etc/cinder/fc.xml
      volume_backend_name = FC

      [DXISCSI]
      volume_driver = cinder.volume.drivers.fujitsu.eternus_dx_iscsi.FJDXISCSIDriver
      cinder_eternus_config_file = /etc/cinder/iscsi.xml
      volume_backend_name = ISCSI

#. Create the driver configuration files ``fc.xml`` and ``iscsi.xml``.

#. Create a volume type and set extra specs to the type:

   .. code-block:: console

      $ openstack volume type create DX_FC
      $ openstack volume type set --property volume_backend_name=FC DX_FX
      $ openstack volume type create DX_ISCSI
      $ openstack volume type set --property volume_backend_name=ISCSI DX_ISCSI

   By issuing these commands,
   the volume type ``DX_FC`` is associated with the ``FC``,
   and the type ``DX_ISCSI`` is associated with the ``ISCSI``.
