=============================================
Seagate Array Fibre Channel and iSCSI drivers
=============================================

The ``STXFCDriver`` and ``STXISCSIDriver`` Cinder drivers allow the
Seagate Technology (STX) storage arrays to be used for Block Storage in
OpenStack deployments.

System requirements
~~~~~~~~~~~~~~~~~~~

To use the Seagate drivers, the following are required:

- Seagate storage array with:

  - iSCSI or FC host interfaces
  - G28x firmware or later

- Network connectivity between the OpenStack host and the array management
  interfaces

- The HTTPS or HTTP protocol must be enabled on the array

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, delete, attach, and detach volumes.
- Create, list, and delete volume snapshots.
- Create a volume from a snapshot.
- Copy an image to a volume.
- Copy a volume to an image.
- Clone a volume.
- Extend a volume.
- Migrate a volume with back-end assistance.
- Retype a volume.
- Manage and unmanage a volume.

Configuring the array
~~~~~~~~~~~~~~~~~~~~~

#. Verify that the array can be managed via an HTTPS connection. HTTP can also
   be used if ``driver_use_ssl`` is set to (or defaults to) False
   in the ``cinder.conf`` file.

   Confirm that virtual pools A and B are present if you plan to use virtual
   pools for OpenStack storage.

   If you plan to use vdisks instead of virtual pools, create or identify one
   or more vdisks to be used for OpenStack storage; typically this will mean
   creating or setting aside one disk group for each of the A and B
   controllers.

#. Edit the ``cinder.conf`` file to define a storage back-end entry for each
   storage pool on the array that will be managed by OpenStack. Each entry
   consists of a unique section name, surrounded by square brackets, followed
   by options specified in a ``key=value`` format.

   * The ``seagate_pool_name`` value specifies the name of the storage pool
     or vdisk on the array.

   * The ``volume_backend_name`` option value can be a unique value, if you
     wish to be able to assign volumes to a specific storage pool on the
     array, or a name that is shared among multiple storage pools to let the
     volume scheduler choose where new volumes are allocated.

#. The following ``cinder.conf`` options generally have identical values
   for each backend section on the array:

   * ``volume_driver`` specifies the Cinder driver name.

   * ``san_ip`` specifies the IP addresses or host names of the array's
     management controllers.

   * ``san_login`` and ``san_password`` specify the username and password
     of an array user account with ``manage`` privileges

   * ``driver_use_ssl`` must be set to True to enable use of the HTTPS
     protocol.

   * ``seagate_iscsi_ips`` specfies the iSCSI IP addresses
     for the array if using the iSCSI transport protocol

   In the examples below, two back ends are defined, one for pool A and one for
   pool B, and a common ``volume_backend_name`` is used so that a single
   volume type definition can be used to allocate volumes from both pools.

   **iSCSI example back-end entries**

   .. code-block:: ini

      [pool-a]
      seagate_pool_name = A
      volume_backend_name = seagate-array
      volume_driver = cinder.volume.drivers.stx.iscsi.STXISCSIDriver
      san_ip = 10.1.2.3,10.1.2.4
      san_login = manage
      san_password = !manage
      seagate_iscsi_ips = 10.2.3.4,10.2.3.5
      driver_use_ssl = true

      [pool-b]
      seagate_backend_name = B
      volume_backend_name = seagate-array
      volume_driver = cinder.volume.drivers.stx.iscsi.STXISCSIDriver
      san_ip = 10.1.2.3,10.1.2.4
      san_login = manage
      san_password = !manage
      seagate_iscsi_ips = 10.2.3.4,10.2.3.5
      driver_use_ssl = true

   **Fibre Channel example back-end entries**

   .. code-block:: ini

      [pool-a]
      seagate_backend_name = A
      volume_backend_name = seagate-array
      volume_driver = cinder.volume.drivers.stx.fc.STXFCDriver
      san_ip = 10.1.2.3,10.1.2.4
      san_login = manage
      san_password = !manage
      driver_use_ssl = true

      [pool-b]
      seagate_backend_name = B
      volume_backend_name = seagate-array
      volume_driver = cinder.volume.drivers.stx.fc.STXFCDriver
      san_ip = 10.1.2.3,10.1.2.4
      san_login = manage
      san_password = !manage
      driver_use_ssl = true

#. If any ``volume_backend_name`` value refers to a vdisk rather than a
   virtual pool, add an additional statement ``seagate_backend_type = linear``
   to that back-end entry.

#. If HTTPS is enabled, you can enable certificate verification with the option
   ``driver_ssl_cert_verify = True``. You may also use the
   ``driver_ssl_cert_path`` parameter to specify the path to a
   CA\_BUNDLE file containing CAs other than those in the default list.

#. Modify the ``[DEFAULT]`` section of the ``cinder.conf`` file to add an
   ``enabled_backends`` parameter specifying the backend entries you added,
   and a ``default_volume_type`` parameter specifying the name of a volume type
   that you will create in the next step.

   **Example of [DEFAULT] section changes**

   .. code-block:: ini

      [DEFAULT]
      enabled_backends = pool-a,pool-b
      default_volume_type = seagate


#. Create a new volume type for each distinct ``volume_backend_name`` value
   that you added in the ``cinder.conf`` file. The example below assumes that
   the same ``volume_backend_name=seagate-array`` option was specified in all
   of the entries, and specifies that the volume type ``seagate`` can be used
   to allocate volumes from any of them.

   **Example of creating a volume type**

   .. code-block:: console

      $ openstack volume type create seagate
      $ openstack volume type set --property volume_backend_name=seagate-array seagate

#. After modifying the ``cinder.conf`` file, restart the ``cinder-volume``
   service.

Driver-specific options
~~~~~~~~~~~~~~~~~~~~~~~

The following table contains the configuration options that are specific to
the Seagate drivers.

.. config-table::
   :config-target: Seagate

      cinder.volume.drivers.stx.common
