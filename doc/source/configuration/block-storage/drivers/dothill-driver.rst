===================================================
Dot Hill AssuredSAN Fibre Channel and iSCSI drivers
===================================================

The ``DotHillFCDriver`` and ``DotHillISCSIDriver`` volume drivers allow
Dot Hill arrays to be used for block storage in OpenStack deployments.

System requirements
~~~~~~~~~~~~~~~~~~~

To use the Dot Hill drivers, the following are required:

- Dot Hill AssuredSAN array with:

  - iSCSI or FC host interfaces
  - G22x firmware or later
  - Appropriate licenses for the snapshot and copy volume features

- Network connectivity between the OpenStack host and the array
  management interfaces

- HTTPS or HTTP must be enabled on the array

Supported operations
~~~~~~~~~~~~~~~~~~~~~

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

#. Verify that the array can be managed via an HTTPS connection. HTTP can
   also be used if ``dothill_api_protocol=http`` is placed into the
   appropriate sections of the ``cinder.conf`` file.

   Confirm that virtual pools A and B are present if you plan to use
   virtual pools for OpenStack storage.

   If you plan to use vdisks instead of virtual pools, create or identify
   one or more vdisks to be used for OpenStack storage; typically this will
   mean creating or setting aside one disk group for each of the A and B
   controllers.

#. Edit the ``cinder.conf`` file to define an storage back-end entry for
   each storage pool on the array that will be managed by OpenStack. Each
   entry consists of a unique section name, surrounded by square brackets,
   followed by options specified in ``key=value`` format.

   - The ``dothill_backend_name`` value specifies the name of the storage
     pool or vdisk on the array.

   - The ``volume_backend_name`` option value can be a unique value, if
     you wish to be able to assign volumes to a specific storage pool on
     the array, or a name that is shared among multiple storage pools to
     let the volume scheduler choose where new volumes are allocated.

   - The rest of the options will be repeated for each storage pool in a
     given array: the appropriate Cinder driver name; IP address or
     hostname of the array management interface; the username and password
     of an array user account with ``manage`` privileges; and the iSCSI IP
     addresses for the array if using the iSCSI transport protocol.

   In the examples below, two back ends are defined, one for pool A and one
   for pool B, and a common ``volume_backend_name`` is used so that a
   single volume type definition can be used to allocate volumes from both
   pools.


   **iSCSI example back-end entries**

   .. code-block:: ini

      [pool-a]
      dothill_backend_name = A
      volume_backend_name = dothill-array
      volume_driver = cinder.volume.drivers.dothill.dothill_iscsi.DotHillISCSIDriver
      san_ip = 10.1.2.3
      san_login = manage
      san_password = !manage
      dothill_iscsi_ips = 10.2.3.4,10.2.3.5

      [pool-b]
      dothill_backend_name = B
      volume_backend_name = dothill-array
      volume_driver = cinder.volume.drivers.dothill.dothill_iscsi.DotHillISCSIDriver
      san_ip = 10.1.2.3
      san_login = manage
      san_password = !manage
      dothill_iscsi_ips = 10.2.3.4,10.2.3.5

   **Fibre Channel example back-end entries**

   .. code-block:: ini

      [pool-a]
      dothill_backend_name = A
      volume_backend_name = dothill-array
      volume_driver = cinder.volume.drivers.dothill.dothill_fc.DotHillFCDriver
      san_ip = 10.1.2.3
      san_login = manage
      san_password = !manage

      [pool-b]
      dothill_backend_name = B
      volume_backend_name = dothill-array
      volume_driver = cinder.volume.drivers.dothill.dothill_fc.DotHillFCDriver
      san_ip = 10.1.2.3
      san_login = manage
      san_password = !manage

#. If any ``volume_backend_name`` value refers to a vdisk rather than a
   virtual pool, add an additional statement
   ``dothill_backend_type = linear`` to that back-end entry.

#. If HTTPS is not enabled in the array, include
   ``dothill_api_protocol = http`` in each of the back-end definitions.

#. If HTTPS is enabled, you can enable certificate verification with the
   option ``dothill_verify_certificate=True``. You may also use the
   ``dothill_verify_certificate_path`` parameter to specify the path to a
   CA\_BUNDLE file containing CAs other than those in the default list.

#. Modify the ``[DEFAULT]`` section of the ``cinder.conf`` file to add an
   ``enabled_backends`` parameter specifying the back-end entries you added,
   and a ``default_volume_type`` parameter specifying the name of a volume
   type that you will create in the next step.

   **Example of [DEFAULT] section changes**

   .. code-block:: ini

      [DEFAULT]
      # ...
      enabled_backends = pool-a,pool-b
      default_volume_type = dothill
      # ...

#. Create a new volume type for each distinct ``volume_backend_name`` value
   that you added to cinder.conf. The example below assumes that the same
   ``volume_backend_name=dothill-array`` option was specified in all of the
   entries, and specifies that the volume type ``dothill`` can be used to
   allocate volumes from any of them.

   **Example of creating a volume type**

   .. code-block:: console

      $ openstack volume type create dothill
      $ openstack volume type set --property volume_backend_name=dothill-array dothill

#. After modifying ``cinder.conf``, restart the ``cinder-volume`` service.

Driver-specific options
~~~~~~~~~~~~~~~~~~~~~~~

The following table contains the configuration options that are specific
to the Dot Hill drivers.

.. include:: ../../tables/cinder-dothill.inc
