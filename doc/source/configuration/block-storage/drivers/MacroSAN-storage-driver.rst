==========================================
MacroSAN Fibre Channel and iSCSI drivers
==========================================

The ``MacroSANFCDriver`` and ``MacroSANISCSIDriver`` Cinder drivers allow the
MacroSAN Storage arrays to be used for Block Storage in OpenStack deployments.

System requirements
~~~~~~~~~~~~~~~~~~~

To use the MacroSAN drivers, the following are required:

- MacroSAN Storage arrays with:
  - iSCSI or FC host interfaces
  - Enable RESTful service on the MacroSAN Storage Appliance. (The service is
  automatically turned on in the device. You can check if
  `python /odsp/scripts/devop/devop.py` is available via `ps -aux|grep python`.
  )

- Network connectivity between the OpenStack host and the array management
  interfaces

- HTTPS or HTTP must be enabled on the array

When creating a volume from image, install the ``multipath`` tool and add the
following configuration keys in the ``[DEFAULT]`` configuration group of
the ``/etc/cinder/cinder.conf`` file:

.. code-block:: ini

   use_multipath_for_image_xfer = True

When creating a instance from image, install the ``multipath`` tool and add the
following configuration keys in the ``[libvirt]`` configuration group of
the ``/etc/nova/nova.conf`` file:

.. code-block:: ini

   iscsi_use_multipath = True

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, delete, attach, and detach volumes.
- Create, list, and delete volume snapshots.
- Create a volume from a snapshot.
- Copy an image to a volume.
- Copy a volume to an image.
- Clone a volume.
- Extend a volume.
- Volume Migration (Host Assisted).
- Volume Migration (Storage Assisted).
- Retype a volume.
- Manage and unmanage a volume.
- Manage and unmanage a snapshot.
- Volume Replication.
- Thin Provisioning.

Configuring the array
~~~~~~~~~~~~~~~~~~~~~

#. Verify that the array can be managed via an HTTPS connection.

   Confirm that virtual pools A and B are present if you plan to use virtual
   pools for OpenStack storage.

#. Edit the ``cinder.conf`` file to define a storage backend entry for each
   storage pool on the array that will be managed by OpenStack. Each entry
   consists of a unique section name, surrounded by square brackets, followed
   by options specified in a ``key=value`` format.


   * The ``volume_backend_name`` option value can be a unique value, if you
     wish to be able to assign volumes to a specific storage pool on the
     array, or a name that is shared among multiple storage pools to let the
     volume scheduler choose where new volumes are allocated.

   In the examples below, two back ends are defined, one for pool A and one
   for pool B.

   * Add the following configuration keys in the configuration group of
     enabled_backends of the ``/etc/cinder/cinder.conf`` file:

   **iSCSI example back-end entries**

   .. code-block:: ini

      [DEFAULT]
      enabled_backends = cinder-iscsi-a, cinder-iscsi-b
      rpc_response_timeout = 300

      [cinder-iscsi-a]
      # Storage protocol.
      iscsi_protocol = iscsi

      #iSCSI target user-land tool.
      iscsi_helper = tgtadm

      # The iSCSI driver to load
      volume_driver = cinder.volume.drivers.macrosan.driver.MacroSANISCSIDriver.

      # Name to give this storage back-end.
      volume_backend_name = macrosan

      #Choose attach/detach volumes in cinder using multipath for volume to image and image to volume transfers.
      use_multipath_for_image_xfer = True

      # IP address of the Storage if attaching directly.
      san_ip = 172.17.251.142, 172.17.251.143

      # Storage user name.
      san_login = openstack

      # Storage user password.
      san_password = openstack

      #Choose using thin-lun or thick lun. When set san_thin_provision to True,you must set
      #macrosan_thin_lun_extent_size, macrosan_thin_lun_low_watermark, macrosan_thin_lun_high_watermark.
      san_thin_provision = False

      #The name of Pool in the Storage.
      macrosan_pool = Pool-a

      #The default ports used for initializing connection.
      #Separate the controller by semicolons (``;``)
      #Separate the ports by comma (``,``)
      macrosan_client_default = eth-1:0:0, eth-1:0:1; eth-2:0:0, eth-2:0:1

      #The switch to force detach volume when deleting
      macrosan_force_unmap_itl = True

      #Set snapshot's resource ratio
      macrosan_snapshot_resource_ratio = 1

      #Calculate the time spent on the operation in the log file.
      macrosan_log_timing = True

      # =============Optional settings=============

      #Set the thin lun's extent size when the san_thin_provision is True.
      macrosan_thin_lun_extent_size = 8

      #Set the thin lun's low watermark when the san_thin_provision is True.
      #macrosan_thin_lun_low_watermark = 8

      #Set the thin lun's high watermark when the san_thin_provision is True.
      macrosan_thin_lun_high_watermark = 40

      #The setting of Symmetrical Dual Active Storage
      macrosan_sdas_ipaddrs = 172.17.251.142, 172.17.251.143
      macrosan_sdas_username = openstack
      macrosan_sdas_password = openstack

      #The setting of Replication Storage. When you set ip, you must set
      #the macrosan_replication_destination_ports parameter.
      macrosan_replication_ipaddrs = 172.17.251.142, 172.17.251.143
      macrosan_replication_username = openstack
      macrosan_replication_password = openstack

      ##The ports used for the Replication Storage.
      #Separate the controller by semicolons (``,``)
      #Separate the ports by semicolons (``/``)
      macrosan_replication_destination_ports = eth-1:0:0/eth-1:0:1, eth-2:0:0/eth-2:0:1

      #Macrosan iscsi_clients list. You can configure multiple clients. Separate the ports by semicolons (``/``)
      macrosan_client = (devstack; controller1name; eth-1:0:0/eth-1:0:1; eth-2:0:0/eth-2:0:1), (dev; controller2name; eth-1:0:0/eth-1:0:1; eth-2:0:0/eth-2:0:1)

      [cinder-iscsi-b]
      iscsi_protocol = iscsi
      iscsi_helper = tgtadm
      volume_driver = cinder.volume.drivers.macrosan.driver.MacroSANISCSIDriver
      volume_backend_name = macrosan
      use_multipath_for_image_xfer = True
      san_ip = 172.17.251.142, 172.17.251.143
      san_login = openstack
      san_password = openstack
      macrosan_pool = Pool-b
      san_thin_provision = False
      macrosan_force_unmap_itl = True
      macrosan_snapshot_resource_ratio = 1
      macrosan_log_timing = True
      macrosan_client_default = eth-1:0:0, eth-1:0:1; eth-2:0:0, eth-2:0:1

      macrosan_thin_lun_extent_size = 8
      macrosan_thin_lun_low_watermark = 8
      macrosan_thin_lun_high_watermark = 40
      macrosan_sdas_ipaddrs = 172.17.251.142, 172.17.251.143
      macrosan_sdas_username = openstack
      macrosan_sdas_password = openstack
      macrosan_replication_ipaddrs = 172.17.251.142, 172.17.251.143
      macrosan_replication_username = openstack
      macrosan_replication_password = openstack
      macrosan_replication_destination_ports = eth-1:0:0, eth-2:0:0
      macrosan_client = (devstack; controller1name; eth-1:0:0; eth-2:0:0), (dev; controller2name; eth-1:0:0; eth-2:0:0)

   **Fibre Channel example backend entries**

   .. code-block:: ini

      [DEFAULT]
      enabled_backends = cinder-fc-a, cinder-fc-b
      rpc_response_timeout = 300

      [cinder-fc-a]
      volume_driver = cinder.volume.drivers.macrosan.driver.MacroSANFCDriver
      volume_backend_name = macrosan
      use_multipath_for_image_xfer = True
      san_ip = 172.17.251.142, 172.17.251.143
      san_login = openstack
      san_password = openstack
      macrosan_pool = Pool-a
      san_thin_provision = False
      macrosan_force_unmap_itl = True
      macrosan_snapshot_resource_ratio = 1
      macrosan_log_timing = True

      #FC Zoning mode configured.
      zoning_mode = fabric

      #The number of ports used for initializing connection.
      macrosan_fc_use_sp_port_nr = 1

      #In the case of an FC connection, the configuration item associated with the port is maintained.
      macrosan_fc_keep_mapped_ports = True

      # =============Optional settings=============

      macrosan_thin_lun_extent_size = 8
      macrosan_thin_lun_low_watermark = 8
      macrosan_thin_lun_high_watermark = 40
      macrosan_sdas_ipaddrs = 172.17.251.142, 172.17.251.143
      macrosan_sdas_username = openstack
      macrosan_sdas_password = openstack
      macrosan_replication_ipaddrs = 172.17.251.142, 172.17.251.143
      macrosan_replication_username = openstack
      macrosan_replication_password = openstack
      macrosan_replication_destination_ports = eth-1:0:0, eth-2:0:0


      [cinder-fc-b]
      volume_driver = cinder.volume.drivers.macrosan.driver.MacroSANFCDriver
      volume_backend_name = macrosan
      use_multipath_for_image_xfer = True
      san_ip = 172.17.251.142, 172.17.251.143
      san_login = openstack
      san_password = openstack
      macrosan_pool = Pool-b
      san_thin_provision = False
      macrosan_force_unmap_itl = True
      macrosan_snapshot_resource_ratio = 1
      macrosan_log_timing = True
      zoning_mode = fabric
      macrosan_fc_use_sp_port_nr = 1
      macrosan_fc_keep_mapped_ports = True

      macrosan_thin_lun_extent_size = 8
      macrosan_thin_lun_low_watermark = 8
      macrosan_thin_lun_high_watermark = 40
      macrosan_sdas_ipaddrs = 172.17.251.142, 172.17.251.143
      macrosan_sdas_username = openstack
      macrosan_sdas_password = openstack
      macrosan_replication_ipaddrs = 172.17.251.142, 172.17.251.143
      macrosan_replication_username = openstack
      macrosan_replication_password = openstack
      macrosan_replication_destination_ports = eth-1:0:0, eth-2:0:0

#. After modifying the ``cinder.conf`` file, restart the ``cinder-volume``
   service.

#. Create and use volume types.

   **Create and use sdas volume types**

   .. code-block:: console

      $ openstack volume type create sdas
      $ openstack volume type set --property sdas=True sdas

   **Create and use replication volume types**

   .. code-block:: console

      $ openstack volume type create replication
      $ openstack volume type set --property replication_enabled=True replication

Configuration file parameters
-----------------------------

This section describes mandatory and optional configuration file parameters
of the MacroSAN volume driver.

.. list-table:: **Mandatory parameters**
   :widths: 10 10 50 10
   :header-rows: 1

   * - Parameter
     - Default value
     - Description
     - Applicable to
   * - volume_backend_name
     - ``-``
     - indicates the name of the backend
     - All
   * - volume_driver
     - ``cinder.volume.drivers.lvm.LVMVolumeDriver``
     - indicates the loaded driver
     - All
   * - use_multipath_for_image_xfer
     - ``False``
     - Chose attach/detach volumes in cinder using multipath for volume to image and image to volume transfers.
     - All
   * - san_thin_provision
     - ``True``
     - Default volume type setting, True is thin lun, and False is thick lun.
     - All
   * - macrosan_force_unmap_itl
     - ``True``
     - Force detach volume when deleting
     - All
   * - macrosan_log_timing
     - ``True``
     - Calculate the time spent on the operation in the log file.
     - All
   * - macrosan_snapshot_resource_ratio
     - ``1``
     - Set snapshot's resource ratio".
     - All
   * - iscsi_helper
     - ``tgtadm``
     - iSCSI target user-land tool to use.
     - iSCSI
   * - iscsi_protocol
     - ``iscsi``
     - Determines the iSCSI protocol for new iSCSI volumes, created with tgtadm.
     - iSCSI
   * - macrosan_client_default
     - ``None``
     - This is the default connection information for iscsi. This default configuration is used when no host related information is obtained.
     - iSCSI
   * - zoning_mode
     - ``True``
     - FC Zoning mode configured.
     - Fibre channel
   * - macrosan_fc_use_sp_port_nr
     - ``1``
     - The use_sp_port_nr parameter is the number of online FC ports used by the single-ended memory when the FC connection is established in the switch non-all-pass mode. The maximum is 4.
     - Fibre channel
   * - macrosan_fc_keep_mapped_ports
     - ``True``
     - In the case of an FC connection, the configuration item associated with the port is maintained.
     - Fibre channel

.. list-table:: **Optional parameters**
   :widths: 20 10 50 15
   :header-rows: 1

   * - Parameter
     - Default value
     - Description
     - Applicable to
   * - macrosan_sdas_ipaddrs
     - ``-``
     - The ip of Symmetrical Dual Active Storage
     - All
   * - macrosan_sdas_username
     - ``-``
     - The username of Symmetrical Dual Active Storage
     - All
   * - macrosan_sdas_password
     - ``-``
     - The password of Symmetrical Dual Active Storage
     - All
   * - macrosan_replication_ipaddrs
     - ``-``
     - The ip of replication Storage. When you set ip, you must set
       the macrosan_replication_destination_ports parameter.
     - All
   * - macrosan_replication_username
     - ``-``
     - The username of replication Storage
     - All
   * - macrosan_replication_password
     - ``-``
     - The password of replication Storage
     - All
   * - macrosan_replication_destination_ports
     - ``-``
     - The ports of replication storage when using replication storage.
     - All
   * - macrosan_thin_lun_extent_size
     - ``8``
     - Set the thin lun's extent size when the san_thin_provision is True.
     - All
   * - macrosan_thin_lun_low_watermark
     - ``5``
     - Set the thin lun's low watermark when the san_thin_provision is True.
     - All
   * - macrosan_thin_lun_high_watermark
     - ``20``
     - Set the thin lun's high watermark when the san_thin_provision is True.
     - All
   * - macrosan_client
     - ``True``
     - Macrosan iscsi_clients list. You can configure multiple clients.
       You can configure it in this format:
       (hostname; client_name; sp1_iscsi_port; sp2_iscsi_port),
       E.g:
       (controller1; decive1; eth-1:0:0; eth-2:0:0),(controller2; decive2; eth-1:0:0/ eth-1:0:1; eth-2:0:0/ eth-2:0:1)
     - All

.. important::

     Client_name has the following requirements:
                    [a-zA-Z0-9.-_:], the maximum number of characters is 31

The following are the MacroSAN driver specific options that may be set in
`cinder.conf`:

.. config-table::
   :config-target: MacroSAN

   cinder.volume.drivers.macrosan.config

