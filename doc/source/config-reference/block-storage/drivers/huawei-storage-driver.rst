====================
Huawei volume driver
====================

Huawei volume driver can be used to provide functions such as the logical
volume and snapshot for virtual machines (VMs) in the OpenStack Block Storage
driver that supports iSCSI and Fibre Channel protocols.

Version mappings
~~~~~~~~~~~~~~~~

The following table describes the version mappings among the Block Storage
driver, Huawei storage system and OpenStack:

.. list-table:: **Version mappings among the Block Storage driver and Huawei
   storage system**
   :widths: 30 35
   :header-rows: 1

   * - Description
     - Storage System Version
   * - Create, delete, expand, attach, detach, manage and unmanage volumes

       Create volumes with assigned storage pools

       Create volumes with assigned disk types

       Create, delete and update a consistency group

       Copy an image to a volume

       Copy a volume to an image

       Auto Zoning

       SmartThin

       Volume Migration

       Replication V2.1

       Create, delete, manage, unmanage and backup snapshots

       Create and delete a cgsnapshot
     - OceanStor T series V2R2 C00/C20/C30

       OceanStor V3 V3R1C10/C20 V3R2C10 V3R3C00/C10/C20

       OceanStor 2200V3 V300R005C00

       OceanStor 2600V3 V300R005C00

       OceanStor 18500/18800 V1R1C00/C20/C30 V3R3C00

       OceanStor Dorado V300R001C00

       OceanStor V3 V300R006C00

       OceanStor 2200V3 V300R006C00

       OceanStor 2600V3 V300R006C00
   * - Clone a volume

       Create volume from snapshot

       Retype

       SmartQoS

       SmartTier

       SmartCache

       Thick
     - OceanStor T series V2R2 C00/C20/C30

       OceanStor V3 V3R1C10/C20 V3R2C10 V3R3C00/C10/C20

       OceanStor 2200V3 V300R005C00

       OceanStor 2600V3 V300R005C00

       OceanStor 18500/18800V1R1C00/C20/C30

       OceanStor V3 V300R006C00

       OceanStor 2200V3 V300R006C00

       OceanStor 2600V3 V300R006C00
   * - SmartPartition
     - OceanStor T series V2R2 C00/C20/C30

       OceanStor V3 V3R1C10/C20 V3R2C10 V3R3C00/C10/C20

       OceanStor 2600V3 V300R005C00

       OceanStor 18500/18800V1R1C00/C20/C30

       OceanStor V3 V300R006C00

       OceanStor 2600V3 V300R006C00
   * - Hypermetro

       Hypermetro consistency group
     - OceanStor V3 V3R3C00/C10/C20

       OceanStor 2600V3 V3R5C00

       OceanStor 18500/18800 V3R3C00

       OceanStor Dorado V300R001C00

       OceanStor V3 V300R006C00

       OceanStor 2600V3 V300R006C00

Volume driver configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section describes how to configure the Huawei volume driver for either
iSCSI storage or Fibre Channel storage.

**Pre-requisites**

When creating a volume from image, install the ``multipath`` tool and add the
following configuration keys in the ``[DEFAULT]`` configuration group of
the ``/etc/cinder/cinder.conf`` file:

.. code-block:: ini

   use_multipath_for_image_xfer = True
   enforce_multipath_for_image_xfer = True

To configure the volume driver, follow the steps below:

#. In ``/etc/cinder``, create a Huawei-customized driver configuration file.
   The file format is XML.
#. Change the name of the driver configuration file based on the site
   requirements, for example, ``cinder_huawei_conf.xml``.
#. Configure parameters in the driver configuration file.

   Each product has its own value for the ``Product`` parameter under the
   ``Storage`` xml block. The full xml file with the appropriate ``Product``
   parameter is as below:

   .. code-block:: xml

      <?xml version="1.0" encoding="UTF-8"?>
         <config>
            <Storage>
               <Product>PRODUCT</Product>
               <Protocol>PROTOCOL</Protocol>
               <UserName>xxxxxxxx</UserName>
               <UserPassword>xxxxxxxx</UserPassword>
               <RestURL>https://x.x.x.x:8088/deviceManager/rest/</RestURL>
            </Storage>
            <LUN>
               <LUNType>xxx</LUNType>
               <WriteType>xxx</WriteType>
               <Prefetch Type="xxx" Value="xxx" />
               <StoragePool>xxx</StoragePool>
            </LUN>
            <iSCSI>
               <DefaultTargetIP>x.x.x.x</DefaultTargetIP>
               <Initiator Name="xxxxxxxx" TargetIP="x.x.x.x"/>
            </iSCSI>
            <Host OSType="Linux" HostIP="x.x.x.x, x.x.x.x"/>
         </config>

    The corresponding ``Product`` values for each product are as below:


   * **For T series V2**

     .. code-block:: xml

        <Product>TV2</Product>

   * **For V3**

     .. code-block:: xml

        <Product>V3</Product>

   * **For OceanStor 18000 series**

     .. code-block:: xml

        <Product>18000</Product>

   * **For OceanStor Dorado series**

     .. code-block:: xml

        <Product>Dorado</Product>

   The ``Protocol`` value to be used is ``iSCSI`` for iSCSI and ``FC`` for
   Fibre Channel as shown below:

   .. code-block:: xml

      # For iSCSI
      <Protocol>iSCSI</Protocol>

      # For Fibre channel
      <Protocol>FC</Protocol>

   .. note::

      For details about the parameters in the configuration file, see the
      `Configuration file parameters`_ section.

#. Configure the ``cinder.conf`` file.

   In the ``[default]`` block of ``/etc/cinder/cinder.conf``,
   enable the ``VOLUME_BACKEND``:

   .. code-block:: ini

      enabled_backends = VOLUME_BACKEND


   Add a new block ``[VOLUME_BACKEND]``, and add the following contents:

   .. code-block:: ini

      [VOLUME_BACKEND]
      volume_driver = VOLUME_DRIVER
      cinder_huawei_conf_file = /etc/cinder/cinder_huawei_conf.xml
      volume_backend_name = Huawei_Storage

   * ``volume_driver`` indicates the loaded driver.

   * ``cinder_huawei_conf_file`` indicates the specified Huawei-customized
     configuration file.

   * ``volume_backend_name`` indicates the name of the backend.

   Add information about remote devices in ``/etc/cinder/cinder.conf``
   in target backend block for ``Hypermetro``.

   .. code-block:: ini

      [VOLUME_BACKEND]
      volume_driver = VOLUME_DRIVER
      cinder_huawei_conf_file = /etc/cinder/cinder_huawei_conf.xml
      volume_backend_name = Huawei_Storage
      metro_san_user = xxx
      metro_san_password = xxx
      metro_domain_name = xxx
      metro_san_address = https://x.x.x.x:8088/deviceManager/rest/
      metro_storage_pools = xxx

   Add information about remote devices in ``/etc/cinder/cinder.conf``
   in target backend block for ``Replication``.

   .. code-block:: ini

      [VOLUME_BACKEND]
      volume_driver = VOLUME_DRIVER
      cinder_huawei_conf_file = /etc/cinder/cinder_huawei_conf.xml
      volume_backend_name = Huawei_Storage
      replication_device =
          backend_id: xxx,
          storage_pool :xxx,
          san_address: https://x.x.x.x:8088/deviceManager/rest/,
          san_user: xxx,
          san_passowrd: xxx,
          iscsi_default_target_ip: x.x.x.x

   .. note::

      By default, the value for ``Hypermetro`` and  ``Replication`` is
      ``None``. For details about the parameters in the configuration file,
      see the `Configuration file parameters`_ section.

   The ``volume-driver`` value for every product is as below:

   .. code-block:: ini

      # For iSCSI
      volume_driver = cinder.volume.drivers.huawei.huawei_driver.HuaweiISCSIDriver

      # For FC
      volume_driver = cinder.volume.drivers.huawei.huawei_driver.HuaweiFCDriver

#. Run the :command:`service cinder-volume restart` command to restart the
   Block Storage service.

Configuring iSCSI Multipathing
------------------------------

To configure iSCSI Multipathing, follow the steps below:

#. Add the port group settings in the Huawei-customized driver configuration
   file and configure the port group name needed by an initiator.

   .. code-block:: xml

      <iSCSI>
         <DefaultTargetIP>x.x.x.x</DefaultTargetIP>
         <Initiator Name="xxxxxx" TargetPortGroup="xxxx" />
      </iSCSI>

#. Enable the multipathing switch of the Compute service module.

   Add ``volume_use_multipath = True`` in ``[libvirt]`` of
   ``/etc/nova/nova.conf``.

#. Run the :command:`service nova-compute restart` command to restart the
   ``nova-compute`` service.

Configuring FC Multipathing
------------------------------

To configure FC Multipathing, follow the steps below:

#. Enable the multipathing switch of the Compute service module.

   Add ``volume_use_multipath = True`` in ``[libvirt]`` of
   ``/etc/nova/nova.conf``.

#. Run the :command:`service nova-compute restart` command to restart the
   ``nova-compute`` service.

Configuring CHAP and ALUA
-------------------------

On a public network, any application server whose IP address resides on the
same network segment as that of the storage systems iSCSI host port can access
the storage system and perform read and write operations in it. This poses
risks to the data security of the storage system. To ensure the storage
systems access security, you can configure ``CHAP`` authentication to control
application servers access to the storage system.

Adjust the driver configuration file as follows:

.. code-block:: xml

   <Initiator ALUA="xxx" CHAPinfo="xxx" Name="xxx" TargetIP="x.x.x.x"/>

``ALUA`` indicates a multipathing mode. 0 indicates that ``ALUA`` is disabled.
1 indicates that ``ALUA`` is enabled. ``CHAPinfo`` indicates the user name and
password authenticated by ``CHAP``. The format is ``mmuser; mm-user@storage``.
The user name and password are separated by semicolons (``;``).

Configuring multiple storage
----------------------------

Multiple storage systems configuration example:

.. code-block:: ini

   enabled_backends = v3_fc, 18000_fc
   [v3_fc]
   volume_driver = cinder.volume.drivers.huawei.huawei_driver.HuaweiFCDriver
   cinder_huawei_conf_file = /etc/cinder/cinder_huawei_conf_v3_fc.xml
   volume_backend_name = huawei_v3_fc
   [18000_fc]
   volume_driver = cinder.volume.drivers.huawei.huawei_driver.HuaweiFCDriver
   cinder_huawei_conf_file = /etc/cinder/cinder_huawei_conf_18000_fc.xml
   volume_backend_name = huawei_18000_fc

Configuration file parameters
-----------------------------

This section describes mandatory and optional configuration file parameters
of the Huawei volume driver.

.. list-table:: **Mandatory parameters**
   :widths: 10 10 50 10
   :header-rows: 1

   * - Parameter
     - Default value
     - Description
     - Applicable to
   * - Product
     - ``-``
     - Type of a storage product. Possible values are ``TV2``, ``18000`` and
       ``V3``.
     - All
   * - Protocol
     - ``-``
     - Type of a connection protocol. The possible value is either ``'iSCSI'``
       or ``'FC'``.
     - All
   * - RestURL
     - ``-``
     - Access address of the REST interface,
       ``https://x.x.x.x/devicemanager/rest/``. The value ``x.x.x.x`` indicates
       the management IP address. OceanStor 18000 uses the preceding setting,
       and V2 and V3 requires you to add port number ``8088``, for example,
       ``https://x.x.x.x:8088/deviceManager/rest/``. If you need to configure
       multiple RestURL, separate them by semicolons (;).
     - All
   * - UserName
     - ``-``
     - User name of a storage administrator.
     - All
   * - UserPassword
     - ``-``
     - Password of a storage administrator.
     - All
   * - StoragePool
     - ``-``
     - Name of a storage pool to be used. If you need to configure multiple
       storage pools, separate them by semicolons (``;``).
     - All

.. note::

   The value of ``StoragePool`` cannot contain Chinese characters.

.. list-table:: **Optional parameters**
   :widths: 20 10 50 15
   :header-rows: 1

   * - Parameter
     - Default value
     - Description
     - Applicable to
   * - LUNType
     - Thick
     - Type of the LUNs to be created. The value can be ``Thick`` or ``Thin``. Dorado series only support ``Thin`` LUNs.
     - All
   * - WriteType
     - 1
     - Cache write type, possible values are: ``1`` (write back), ``2``
       (write through), and ``3`` (mandatory write back).
     - All
   * - LUNcopyWaitInterval
     - 5
     - After LUN copy is enabled, the plug-in frequently queries the copy
       progress. You can set a value to specify the query interval.
     - All
   * - Timeout
     - 432000
     - Timeout interval for waiting LUN copy of a storage device to complete.
       The unit is second.
     - All
   * - Initiator Name
     - ``-``
     - Name of a compute node initiator.
     - All
   * - Initiator TargetIP
     - ``-``
     - IP address of the iSCSI port provided for compute nodes.
     - All
   * - Initiator TargetPortGroup
     - ``-``
     - IP address of the iSCSI target port that is provided for compute
       nodes.
     - All
   * - DefaultTargetIP
     - ``-``
     - Default IP address of the iSCSI target port that is provided for
       compute nodes.
     - All
   * - OSType
     - Linux
     - Operating system of the Nova compute node's host.
     - All
   * - HostIP
     - ``-``
     - IP address of the Nova compute node's host.
     - All
   * - metro_san_user
     - ``-``
     - User name of a storage administrator of hypermetro remote device.
     - V3R3/2600 V3R5/18000 V3R3
   * - metro_san_password
     - ``-``
     - Password of a storage administrator of hypermetro remote device.
     - V3R3/2600 V3R5/18000 V3R3
   * - metro_domain_name
     - ``-``
     - Hypermetro domain name configured on ISM.
     - V3R3/2600 V3R5/18000 V3R3
   * - metro_san_address
     - ``-``
     - Access address of the REST interface, https://x.x.x.x/devicemanager/rest/. The value x.x.x.x indicates the management IP address.
     - V3R3/2600 V3R5/18000 V3R3
   * - metro_storage_pools
     - ``-``
     - Remote storage pool for hypermetro.
     - V3R3/2600 V3R5/18000 V3R3
   * - backend_id
     - ``-``
     - Target device ID.
     - All
   * - storage_pool
     - ``-``
     - Pool name of target backend when failover for replication.
     - All
   * - san_address
     - ``-``
     - Access address of the REST interface, https://x.x.x.x/devicemanager/rest/. The value x.x.x.x indicates the management IP address.
     - All
   * - san_user
     - ``-``
     - User name of a storage administrator of replication remote device.
     - All
   * - san_password
     - ``-``
     - Password of a storage administrator of replication remote device.
     - All
   * - iscsi_default_target_ip
     - ``-``
     - Remote transacton port IP.
     - All
.. important::

   The ``Initiator Name``, ``Initiator TargetIP``, and
   ``Initiator TargetPortGroup`` are ``ISCSI`` parameters and therefore not
   applicable to ``FC``.
