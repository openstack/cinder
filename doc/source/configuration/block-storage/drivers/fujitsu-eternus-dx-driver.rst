=========================
Fujitsu ETERNUS DX driver
=========================

Fujitsu ETERNUS DX driver provides FC and iSCSI support for
ETERNUS DX series.

The driver performs volume operations by communicating with
ETERNUS DX. It uses a CIM client in Python called PyWBEM
to perform CIM operations over HTTP.

You can specify RAID Group and Thin Provisioning Pool (TPP)
in ETERNUS DX as a storage pool.

System requirements
~~~~~~~~~~~~~~~~~~~

Supported storages:

* ETERNUS AF150 S3
* ETERNUS AF250 S3/AF250 S2/AF250
* ETERNUS AF650 S3/AF650 S2/AF650
* ETERNUS DX200F
* ETERNUS DX60 S5/S4/S3
* ETERNUS DX100 S5/S4/S3
* ETERNUS DX200 S5/S4/S3
* ETERNUS DX500 S5/S4/S3
* ETERNUS DX600 S5/S4/S3
* ETERNUS DX8700 S3/DX8900 S4/S3

Requirements:

* Firmware version V10L30 or later is required.
* The multipath environment with ETERNUS Multipath Driver is unsupported.
* An Advanced Copy Feature license is required
  to create snapshots, create volume from snapshots, or clone volumes.

Supported operations
~~~~~~~~~~~~~~~~~~~~

* Create, delete, attach, and detach volumes.
* Create, list, and delete volume snapshots.
* Create a volume from a snapshot.
* Copy an image to a volume.
* Copy a volume to an image.
* Clone a volume.
* Extend a volume.
* Get volume statistics.
* Migrate Volume.
* Revert a volume to snapshot.

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
     ETERNUS CLI User's Guide for ETERNUS DX series.

#. Create an account with software role for communication
   with cinder controller.

#. Enable the SMI-S of ETERNUS DX.

#. Register an Advanced Copy Feature license and configure copy table size.

#. Create a storage pool for volumes.

#. (Optional) If you want to create snapshots
   on a different storage pool for volumes,
   create a storage pool for snapshots.

#. Create Snap Data Pool Volume (SDPV) to enable Snap Data Pool (SDP) for
   ``create a snapshot``.

#. Configure storage ports to be used by the Block Storage service.

   * Set those storage ports to CA mode.
   * Enable the host-affinity settings of those storage ports.

     (ETERNUS CLI command for enabling host-affinity settings):

     .. code-block:: console

        CLI> set fc-parameters -host-affinity enable -port <CM#><CA#><Port>
        CLI> set iscsi-parameters -host-affinity enable -port <CM#><CA#><Port>

   .. note::
      * Replace <CM#> and <CA#> with the name of the controller enclosure where the port is located.
      * Replace <Port> with the port number.

#. Ensure LAN connection between cinder controller and MNT port of ETERNUS DX
   and SAN connection between Compute nodes and CA ports of ETERNUS DX.

#. (Optional) If you want to use a public key to SSH to the ETERNUS DX storage,
   generate the SSH key, and upload the ``eternus.ietf`` file to the ETERNUS
   storage.

   For information about how to set the public key, refer to the ETERNUS Web
   GUI manuals.

   .. code-block:: console

      $ ssh-keygen -t rsa -N "" -f ./eternus -m PEM
      $ ssh-keygen -e -f ./eternus.pub > ./eternus.ietf

   If the public key(eternus.ietf) that was created is deleted by mistake, use
   the following command to recreate the key.

   .. code-block:: console

      $ ssh-keygen -e -f /root/.ssh/eternus.pub > ./eternus.ietf

Configuration
~~~~~~~~~~~~~

#. Add the following entries to ``/etc/cinder/cinder.conf``:

   FC entries:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.fujitsu.eternus_dx.eternus_dx_fc.FJDXFCDriver
      cinder_eternus_config_file = /etc/cinder/eternus_dx.xml

   iSCSI entries:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.fujitsu.eternus_dx.eternus_dx_iscsi.FJDXISCSIDriver
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
       <EternusPool>tpp_0001</EternusPool>
       <EternusPool>raid_0002</EternusPool>
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
       <EternusPool>tpp_0001</EternusPool>
       <EternusPool>raid_0002</EternusPool>
       <EternusSnapPool>raid5_0001</EternusSnapPool>
       <EternusISCSIIP>1.1.1.1</EternusISCSIIP>
       <EternusISCSIIP>1.1.1.2</EternusISCSIIP>
       <EternusISCSIIP>1.1.1.3</EternusISCSIIP>
       <EternusISCSIIP>1.1.1.4</EternusISCSIIP>
       </FUJITSU>

   Where:

   ``EternusIP``
       IP address of the SMI-S connection of the ETRENUS device.

       Use the IP address of the MNT port of device.

   ``EternusPort``
       Port number for the SMI-S connection port of the ETERNUS device.

   ``EternusUser``
       User name of ``sofware`` role for the connection ``EternusIP``.

   ``EternusPassword``
       Corresponding password of ``EternusUser`` on ``EternusIP``.

   ``EternusPool`` (Multiple setting allowed)
       Name of the storage pool for the volumes from ``ETERNUS DX setup``.

       Use the pool RAID Group pool name or TPP pool name in the ETERNUS device.

   ``EternusSnapPool`` (Multiple setting allowed)
       Name of the storage pool for the snapshots from ``ETERNUS DX setup``.

       Use the pool RAID Group pool name or TPP pool name in the ETERNUS device.

       If you did not create a different pool for snapshots, use the same value as ``EternusPool``.

   ``EternusISCSIIP`` (Multiple setting allowed)
       iSCSI connection IP address of the ETERNUS DX.

   .. note::

      * You can specify the same RAID Group pool name or TPP pool name for ``EternusPool`` and ``EternusSnapPool``
        if you create volumes and snapshots on a same storage pool.
      * For ``EternusPool``, when multiple pools are specified,
        cinder-scheduler will select one from multiple pools to create the volume.

Configuration example
~~~~~~~~~~~~~~~~~~~~~

#. Edit ``cinder.conf``:

   .. code-block:: ini

      [DEFAULT]
      enabled_backends = DXFC, DXISCSI

      [DXFC]
      volume_driver = cinder.volume.drivers.fujitsu.eternus_dx.eternus_dx_fc.FJDXFCDriver
      cinder_eternus_config_file = /etc/cinder/fc.xml
      volume_backend_name = FC
      fujitsu_passwordless = False

      [DXISCSI]
      volume_driver = cinder.volume.drivers.fujitsu.eternus_dx.eternus_dx_iscsi.FJDXISCSIDriver
      cinder_eternus_config_file = /etc/cinder/iscsi.xml
      volume_backend_name = ISCSI
      fujitsu_passwordless = True
      fujitsu_private_key_path = /etc/cinder/eternus

#. Create the driver configuration files ``fc.xml`` and ``iscsi.xml``.

#. Create a volume type and set extra specs to the type:

   .. code-block:: console

      $ cinder type-create DX_FC
      $ cinder type-key DX_FX set volume_backend_name=FC
      $ cinder type-create DX_ISCSI
      $ cinder type-key DX_ISCSI set volume_backend_name=ISCSI

   By issuing these commands,
   the volume type ``DX_FC`` is associated with the ``FC``,
   and the type ``DX_ISCSI`` is associated with the ``ISCSI``.


Supported Functions of the ETERNUS OpenStack VolumeDriver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Migrate Volume
--------------

Moves volumes to a different storage pool.

#. ETERNUS AF/DX functions

   * Creates migration destination volumes / deletes migration
     source volumes.

   * Sets access paths to migration volumes / deletes migration
     access paths to migration source volumes.

   * Uses Create Volume, Delete Volume, Attach Volume and Detach
     Volume.

#. Cinder operation

   * Copies data in the migration source volume to the migration
     destination volume.

.. note::

   Host information must be specified in Migrated Volume.

   The input format is as follows:

   ``Host-Name@Backend-Name#Pool-Name``

   For the following environment or settings, specify
   ``test.localhost@Backend1#PoolA`` for the host.

   * PoolA is a  pool specified in ``/etc/cinder/cinder_fujitsu_eternus_dx.xml``.

    .. code-block:: console

      $ hostname
        test.localhost

      $ cat /etc/cinder/cinder.conf
        (snip)
        [Backend1]
        volume_driver=cinder.volume.drivers.fujitsu.eternus_dx.eternus_dx_fc.FJDXFCDriver
        cinder_eternus_config_file = /etc/cinder/cinder_fujitsu_eternus_dx.xml
        volume_backend_name=volume_backend_name1

.. warning::

   There are some restrictions for volume migration:

   #. You cannot migrate a volume that has snapshots.

   #. You cannot use driver-assisted migration to move a volume to or from a
      backend that does not use the ETERNUS OpenStack volume driver.


Supplementary Information for the Supported Functions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

QoS Settings
------------

The QoS settings that are linked with the volume QoS function of the
ETERNUS AF/DX are available.

An upper limit value of the bandwidth(BWS) can be set for each volume.
A lower limit value can not be set.

The upper limit is set if the firmware version of the ETERNUS AF/DX is
earlier than V11L30, and the IOPS/Throughput of
Total/Read/Write for the volume is set separately for V11L30 and later.

The following procedure shows how to set the QoS.

#. Create a QoS definition.

   * The firmware version of the ETERNUS AF/DX is earlier than V11L30

   .. code-block:: ini

      $ cinder qos-create <qos_name> maxBWS=xx

   For <qos_name>, specify the name of the definition that is to be created.

   For maxBWS, specify a value in MB.

   * The firmware version of the ETERNUS AF/DX is V11L30 or later

   .. code-block:: console

      $ cinder qos-create <qos_name> read_iops_sec=15000 write_iops_sec=12600 total_iops_sec=15000 read_bytes_sec=800 write_bytes_sec=700 total_bytes_sec=800

#. When not using the existing volume type, create a new volume type.

   .. code-block:: console

      $ cinder type-create <volume_type_name>

   For <volume_type_name>, specify the name of the volume type that is to be created.

#. Associate the QoS definition with the volume type.

   .. code-block:: console

      $ cinder qos-associate <qos_specs> <volume_type_id>

   For <qos_specs>, specify the ID of the QoS definition that was created.

   For <volume_type_id>, specify the ID of the volume type that was created.

**Cautions**

#. For the procedure to cancel the QoS settings,
   refer to "OpenStack Command-Line Interface Reference".

#. The QoS mode of the ETERNUS AF/DX must be enabled in advance.
   For details, refer to the ETERNUS Web GUI manuals.

#. When the firmware version of the ETERNUS AF/DX is earlier than V11L30,
   for the volume QoS settings of the ETERNUS AF/DX, upper limits are set
   using the predefined options.

   Therefore, set the upper limit of the ETERNUS AF/DX side to a maximum value
   that does not exceed the specified maxBWS.

   The following table shows the upper limits that can be set on the
   ETERNUS AF/DX side and example settings.
   For details about the volume QoS settings of the ETERNUS AF/DX,
   refer to the ETERNUS Web GUI manuals.

   +--------------------------------+
   | Settings for the ETERNUS AF/DX |
   +================================+
   | Unlimited                      |
   +--------------------------------+
   | 15000 IOPS (800MB/s)           |
   +--------------------------------+
   | 12600 IOPS (700MB/s)           |
   +--------------------------------+
   | 10020 IOPS (600MB/s)           |
   +--------------------------------+
   | 7500 IOPS (500MB/s)            |
   +--------------------------------+
   | 5040 IOPS (400MB/s)            |
   +--------------------------------+
   | 3000 IOPS (300MB/s)            |
   +--------------------------------+
   | 1020 IOPS (200MB/s)            |
   +--------------------------------+
   | 780 IOPS (100MB/s)             |
   +--------------------------------+
   | 600 IOPS (70MB/s)              |
   +--------------------------------+
   | 420 IOPS (40MB/s)              |
   +--------------------------------+
   | 300 IOPS (25MB/s)              |
   +--------------------------------+
   | 240 IOPS (20MB/s)              |
   +--------------------------------+
   | 180 IOPS (15MB/s)              |
   +--------------------------------+
   | 120 IOPS (10MB/s)              |
   +--------------------------------+
   | 60 IOPS (5MB/s)                |
   +--------------------------------+

   * When specified maxBWS=750

     "12600 IOPS (700MB/s)" is set on the ETERNUS AF/DX side.

   * When specified maxBWS=900

     "15000 IOPS (800MB/s)" is set on the ETERNUS AF/DX side.

#. While a QoS definition is being created, if an option other than
   maxBWS/read_iops_sec/write_iops_sec/total_iops_sec/read_bytes_sec
   /write_bytes_sec/total_bytes_sec is specified,
   a warning log is output and the QoS information setting is continued.

#. For an ETERNUS AF/DX wth a firmware version of before V11L30,
   if a QoS definition volume type that is set with read_iops_sec/
   write_iops_sec/total_iops_sec/read_bytes_sec/write_bytes_sec/total_bytes_sec
   is specified for Create Volume, a warning log is output
   and the process is terminated.

#. For an ETERNUS AF/DX with a firmware version of V11L30 or later,
   if a QoS definition volume type that is set with maxBWS is specified
   for Create Volume, a warning log is output and the process is terminated.

#. After the firmware of the ETERNUS AF/DX is upgraded from V11L10/V11L2x to
   a newer version, the volume types related to the QoS definition created
   before the firmware upgrade can no longer be used.
   Set a QoS definition and create a new volume type.

#. When the firmware of the ETERNUS AF/DX is downgraded to V11L10/V11L2x,
   do not use a volume type linked to a pre-firmware downgrade
   QoS definition, because the QoS definition may work differently from
   ones post-firmware downgrade.
   For the volume, create and link a volume type not associated with
   any QoS definition and after the downgrade, create and link a volume type
   associated with a QoS definition.

#. If Create Volume terminates with an error, Cinder may not invoke
   Delete Volume.

   If volumes are created but the QoS settings fail, the
   ETERNUS OpenStack VolumeDriver ends the process to prevent the
   created volumes from being left in the ETERNUS AF/DX.
   If volumes fail to be created, the process terminates with an error.

Specification of the Snapshot Creation Destination Pool
-------------------------------------------------------

A RAID Group or a Thin Provisioning Pool (TPP) can be specified as the snapshot
creation destination pool. In an ETERNUS AF/DX with a firmware version earlier
than or equal to V10L60, Thin Provisioning Pools(TPPs) cannot be used as the
snapshot creation destination pool.

Multiple snapshot creation destination pools can be specified.

A pool where snapshots can be created is searched in the order written in the
driver configuration file and if one is found, snapshots are created in that
pool.

**Cautions**

#. If the creation destination pool is a RAID Group, more than 128 snapshots
   cannot be created. Therefore, to create more than 128 snapshots in a RAID
   Group, multiple RAID Groups must be specified as snapshot creation
   destination pools.

#. When creating a snapshot, Cinder Scheduler checks the capacity of the pool
   where the source volume is located. This may lead to the failure of snapshot
   creation fail to be created if this pool has insufficient capacity, even if
   the snapshot pool specified by ``EternusSnapPool`` has sufficient capacity.

#. If multiple snapshot creation destination pools are specified, a different
   pool must be specified for the volume creation destination pool
   (``EternusPool`` and ``EternusSnapPool`` can be specified multiple times but
   the same pool name cannot be specified).
   If the same pool name is specified and instructions to create multiple
   volumes and multiple snapshots are issued at the same time, the number of
   logical volumes in a RAID Group will reach 128 and the operation may fail.

#. To address the issue that a volume with snapshot cannot be extended, a
   parameter ``fujitsu_use_cli_copy`` has been introduced.

   The default value of ``fujitsu_use_cli_copy`` is ``False``.

   If ``fujitsu_use_cli_copy`` is set to ``True``, create a Snapshot using the
   CLI method instead of SMI-S method, allowing volume extension of the source
   volume.

    .. code-block:: console

      $ cat /etc/cinder/cinder.conf
        (snip)
        [Backend1]
        volume_driver=cinder.volume.drivers.fujitsu.eternus_dx.eternus_dx_fc.FJDXFCDriver
        cinder_eternus_config_file = /etc/cinder/cinder_fujitsu_eternus_dx.xml
        volume_backend_name = volume_backend_name1
        fujitsu_use_cli_copy = True

   Note that ``fujitsu_use_cli_copy`` cannot be set to True when the type of
   target pool is RAID Group.
