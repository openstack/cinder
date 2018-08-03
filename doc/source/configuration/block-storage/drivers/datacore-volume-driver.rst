==================================
DataCore SANsymphony volume driver
==================================

DataCore SANsymphony volume driver provides OpenStack Compute instances with
access to the SANsymphony(TM) Software-defined Storage Platform.

When volumes are created in OpenStack,  the driver creates corresponding virtual
disks in the SANsymphony server group. When a volume is attached to an instance
in OpenStack, a Linux host is registered and the corresponding virtual disk is
served to the host in the SANsymphony server group.

Requirements
-------------

* DataCore server group running SANsymphony software version 10 PSP6
  or later.

* OpenStack Integration has been tested with the OpenStack environment
  installed on Ubuntu 16.04. For the list of qualified Linux host operating
  system types, refer to the `Linux Host Configuration Guide <https://datacore.custhelp.com/app/answers/detail/a_id/1546>`_
  on the `DataCore Technical Support Web page <https://datacore.custhelp.com/>`_.

* If using multipath I/O, ensure that iSCSI ports are logged in on all
  OpenStack Compute nodes. (All Fibre Channel ports will be logged in
  automatically.)

Python dependencies
~~~~~~~~~~~~~~~~~~~

* ``websocket-client>=0.32.0``

  Install this package using pip:

  .. code-block:: console

     $ sudo pip install "websocket-client>=0.32.0"


Configuration
-------------

The volume driver can be configured by editing the `cinder.conf` file.
The options below can be configured either per server group or as extra
specifications in a volume type configuration.

Configuration options and default values:

* ``datacore_disk_pools = None``

  Sets the pools to use for the DataCore OpenStack Cinder Volume Driver. This
  option acts like a filter and any number of pools may be specified. The list
  of specified pools will be used to select the storage sources needed for
  virtual disks; one for single or two for mirrored. Selection is based on
  the pools with the most free space.

  This option may also be specified as an extra specification of a volume
  type.

* ``datacore_disk_type = single``

  Sets the SANsymphony virtual disk type (single or mirrored). **Single**
  virtual disks are created by default. Specify **mirrored** to override this
  behavior. Mirrored virtual disks require two DataCore Servers in the server
  group.

  This option may also be specified as an extra specification of a volume
  type.

* ``datacore_storage_profile = Normal``

  Sets the storage profile of the virtual disk. The default setting is Normal.
  Other valid values include the standard storage profiles (Critical, High,
  Low, and Archive) and the names of custom profiles that have been created.

  This option may also be specified as an extra specification of a volume
  type.

* ``datacore_api_timeout = 300``

  Sets the number of seconds to wait for a response from a DataCore API call.

  This option is used in the server group back-end configuration only.

* ``datacore_disk_failed_delay = 15``

  Sets the number of seconds to wait for the SANsymphony virtual disk to come
  out of the "Failed" state.

  This option is used in the server group back-end configuration only.

* ``datacore_iscsi_unallowed_targets = []``

  Sets a list of iSCSI targets that cannot be used to attach to the volume.
  By default, the DataCore iSCSI volume driver attaches a volume through all
  target ports with the Front-end role enabled, unlike the DataCore Fibre
  Channel volume driver that attaches a volume only through target ports
  connected to initiator.

  To prevent the DataCore iSCSI volume driver from using some front-end
  targets in volume attachment, specify this option and list the iqn and
  target machine for each target as the value, such as ``<iqn:target name>,
  <iqn:target name>, <iqn:target name>``. For example,
  ``<iqn.2000-08.com.company:Server1-1, iqn.2000-08.com.company:Server2-1,
  iqn.2000-08.com.company:Server3-1>``.

  This option is used in the server group back-end configuration only.

* ``datacore_iscsi_chap_enabled = False``

  Sets the CHAP authentication for the iSCSI targets that are used to serve
  the volume. This option is disabled by default and will allow hosts
  (OpenStack Compute nodes) to connect to iSCSI storage back-ends without
  authentication. To enable CHAP authentication, which will prevent hosts
  (OpenStack Compute nodes) from connecting to back-ends without
  authentication, set this option to **True**.

  In addition, specify the location where the DataCore volume driver will
  store CHAP secrets by setting the **datacore_iscsi_chap_storage option**.

  This option is used in the server group back-end configuration only.
  The driver will enable CHAP only for involved target ports, therefore, not
  all DataCore Servers may have CHAP configured. *Before enabling CHAP, ensure
  that there are no SANsymphony volumes attached to any instances.*

* ``datacore_iscsi_chap_storage = None``

  Sets the path to the iSCSI CHAP authentication password storage file.

  *CHAP secrets are passed from OpenStack Block Storage to compute in clear
  text. This communication should be secured to ensure that CHAP secrets are
  not compromised. This can be done by setting up file permissions. Before
  changing the CHAP configuration, ensure that there are no SANsymphony
  volumes attached to any instances.*

  This option is used in the server group back-end configuration only.

Configuration Examples
~~~~~~~~~~~~~~~~~~~~~~

Examples of option configuration in the ``cinder.conf`` file.

* An example using **datacore_disk_pools**, **datacore_disk_type**, and
  **datacore_storage_profile** to create a mirrored virtual disk with a High
  priority storage profile using specific pools:

  .. code-block:: ini

     volume_driver = cinder.volume.drivers.datacore.iscsi.ISCSIVolumeDriver

     san_ip = <DataCore Server IP or DNS name>

     san_login = <User Name>

     san_password = <Password>

     datacore_disk_type = mirrored

     datacore_disk_pools = Disk pool 1, Disk pool 2

     datacore_storage_profile = High

* An example using **datacore_iscsi_unallowed_targets** to prevent the volume
  from using the specified targets:

  .. code-block:: ini

     volume_driver = cinder.volume.drivers.datacore.iscsi.ISCSIVolumeDriver

     san_ip = <DataCore Server IP or DNS name>

     san_login = <User Name>

     san_password = <Password>

     datacore_iscsi_unallowed_targets = iqn.2000-08.com.datacore:mns-ssv-10-1,iqn.2000-08.com.datacore:mns-ssvdev-01-1

* An example using **datacore_iscsi_chap_enabled** and
  **datacore_iscsi_chap_storage** to enable CHAP authentication and provide
  the path to the CHAP password storage file:

  .. code-block:: ini

     volume_driver = cinder.volume.drivers.datacore.iscsi.ISCSIVolumeDriver

     datacore_iscsi_chap_enabled = True

     datacore_iscsi_chap_storage = /var/lib/cinder/datacore/.chap

  DataCore volume driver stores CHAP secrets in clear text, and the password
  file must be secured by setting up file permissions. The following example
  shows how to create a password file and set up permissions. It assumes that
  the cinder-volume service is running under the user `cinder`.

  .. code-block:: console

     $ sudo mkdir /var/lib/cinder/datacore -p

     $ sudo /bin/sh -c "> /var/lib/cinder/datacore/.chap"

     $ sudo chown cinder:cinder /var/lib/cinder/datacore

     $ sudo chmod -v 750 /var/lib/cinder/datacore

     $ sudo chown cinder:cinder /var/lib/cinder/datacore/.chap

     $ sudo chmod -v 600 /var/lib/cinder/datacore/.chap

  After setting **datacore_iscsi_chap_enabled** and
  **datacore_iscsi_chap_storage**, CHAP authentication will be enabled in
  SANsymphony.

Creating Volume Types
---------------------

Volume types can be created with the DataCore disk type specified in
the datacore:disk_type extra specification. In the following example, a volume
type named mirrored_disk is created and the disk type is set to mirrored.

.. code-block:: console

   $ cinder type-create mirrored_disk

   $ cinder type-key mirrored_disk set datacore:disk_type=mirrored

In addition, volume specifications can also be declared as extra specifications
for volume types. The example below sets additional configuration options for
the volume type mirrored_disk; storage profile will be set to High and virtual
disks will be created from Disk pool 1, Disk pool 2, or Disk pool 3.

.. code-block:: console

   $ cinder type-key mirrored_disk set datacore:storage_profile=High

   $ cinder type-key mirrored_disk set "datacore:disk_pools=Disk pool 1, Disk pool 2, Disk pool 3"

Configuring Multiple Storage Back Ends
--------------------------------------

OpenStack Block Storage can be configured to use several back-end storage
solutions. Multiple back-end configuration allows you to configure different
storage configurations for SANsymphony server groups. The configuration options
for a group must be defined in the group.

To enable multiple back ends:

1. In the ``cinder.conf`` file, set the **enabled_backends** option to identify
   the groups. One name is associated with each server group back-end
   configuration. In the example below there are two groups, ``datacore-1``
   and ``datacore-2``:

   .. code-block:: ini

      [DEFAULT]

      enabled_backends = datacore-1, datacore-2

2. Define the back-end storage used by each server group in a separate section
   (for example ``[datacore-1]``):

   .. code-block:: ini

      [datacore-1]

      volume_driver = cinder.volume.drivers.datacore.iscsi.ISCSIVolumeDriver

      volume_backend_name = DataCore_iSCSI

      san_ip   = <ip_or_dns_name>

      san_login = <user_name>

      san_password = <password>

      datacore_iscsi_chap_enabled = True

      datacore_iscsi_chap_storage = /var/lib/cinder/datacore/.chap

      datacore_iscsi_unallowed_targets = iqn.2000-08.com.datacore:mns-ssv-10-1

      datacore_disk_type = mirrored

      [datacore-2]

      volume_driver = cinder.volume.drivers.datacore.fc.FibreChannelVolumeDriver

      volume_backend_name = DataCore_FibreChannel

      san_ip   = <ip_or_dns_name>

      san_login = <user_name>

      san_password = <password>

      datacore_disk_type = mirrored

      datacore_disk_pools = Disk pool 1, Disk pool 2

      datacore_storage_profile = High

3. Create the volume types

   .. code-block:: ini

      $ cinder type-create datacore_iscsi

      $ cinder type-create datacore_fc

4. Add an extra specification to link the volume type to a back-end name:

   .. code-block:: ini

      $ cinder type-key datacore_iscsi set volume_backend_name=DataCore_iSCSI

      $ cinder type-key datacore_fc set volume_backend_name=DataCore_FibreChannel

See `Configure multiple-storage back ends
<https://docs.openstack.org/cinder/latest/admin/blockstorage-multi-backend.html>`__
for additional information.

Detaching Volumes and Terminating Instances
-------------------------------------------

Notes about the expected behavior of SANsymphony software when detaching volumes
and terminating instances in OpenStack:

1. When a volume is detached from a host in OpenStack, the virtual disk will be
   unserved from the host in SANsymphony, but the  virtual disk will not be
   deleted.

2. If all volumes are detached from a host in OpenStack, the host will remain
   registered and all virtual disks will be unserved from that host in
   SANsymphony. The virtual disks will not be deleted.

3. If an instance is terminated in OpenStack, the virtual disk for the instance
   will be unserved from the host and either be deleted or remain as unserved
   virtual disk depending on the option selected when terminating.

Support
-------

In the event that a support bundle is needed, the administrator should save
the files from the ``/var/log`` folder on the Linux host and attach to DataCore
Technical Support incident manually.
