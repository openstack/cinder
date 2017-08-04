==================
ZTE volume drivers
==================

The ZTE volume drivers allow ZTE KS3200 or KU5200 arrays
to be used for Block Storage in OpenStack deployments.

System requirements
~~~~~~~~~~~~~~~~~~~

To use the ZTE drivers, the following prerequisites:

-  ZTE KS3200 or KU5200 array with:

   -  iSCSI or FC interfaces
   -  30B2 firmware or later

-  Network connectivity between the OpenStack host and the array
   management interfaces

-  HTTPS or HTTP must be enabled on the array

Supported operations
~~~~~~~~~~~~~~~~~~~~

-  Create, delete, attach, and detach volumes.
-  Create, list, and delete volume snapshots.
-  Create a volume from a snapshot.
-  Copy an image to a volume.
-  Copy a volume to an image.
-  Clone a volume.
-  Extend a volume.
-  Migrate a volume with back-end assistance.
-  Retype a volume.
-  Manage and unmanage a volume.

Configuring the array
~~~~~~~~~~~~~~~~~~~~~

#. Verify that the array can be managed using an HTTPS connection. HTTP can
   also be used if ``zte_api_protocol=http`` is placed into the
   appropriate sections of the ``cinder.conf`` file.

   Confirm that virtual pools A and B are present if you plan to use
   virtual pools for OpenStack storage.

#. Edit the ``cinder.conf`` file to define a storage back-end entry for
   each storage pool on the array that will be managed by OpenStack. Each
   entry consists of a unique section name, surrounded by square brackets,
   followed by options specified in ``key=value`` format.

   -  The ``zte_backend_name`` value specifies the name of the storage
      pool on the array.

   -  The ``volume_backend_name`` option value can be a unique value, if
      you wish to be able to assign volumes to a specific storage pool on
      the array, or a name that is shared among multiple storage pools to
      let the volume scheduler choose where new volumes are allocated.

   -  The rest of the options will be repeated for each storage pool in a
      given array: the appropriate cinder driver name, IP address or
      host name of the array management interface; the username and password
      of an array user account with ``manage`` privileges; and the iSCSI IP
      addresses for the array if using the iSCSI transport protocol.

   In the examples below, two back ends are defined, one for pool A and one
   for pool B, and a common ``volume_backend_name``. Use this for a
   single volume type definition can be used to allocate volumes from both
   pools.

   **Example: iSCSI back-end entries**

   .. code-block:: ini

      [pool-a]
      zte_backend_name = A
      volume_backend_name = zte-array
      volume_driver = cinder.volume.drivers.zte.zte_iscsi.ZTEISCSIDriver
      san_ip = 10.1.2.3
      san_login = manage
      san_password = !manage
      zte_iscsi_ips = 10.2.3.4,10.2.3.5

      [pool-b]
      zte_backend_name = B
      volume_backend_name = zte-array
      volume_driver = cinder.volume.drivers.zte.zte_iscsi.ZTEISCSIDriver
      san_ip = 10.1.2.3
      san_login = manage
      san_password = !manage
      zte_iscsi_ips = 10.2.3.4,10.2.3.5

   **Example: Fibre Channel back end entries**

   .. code-block:: ini

      [pool-a]
      zte_backend_name = A
      volume_backend_name = zte-array
      volume_driver = cinder.volume.drivers.zte.zte_fc.ZTEFCDriver
      san_ip = 10.1.2.3
      san_login = manage
      san_password = !manage

      [pool-b]
      zte_backend_name = B
      volume_backend_name = zte-array
      volume_driver = cinder.volume.drivers.zte.zte_fc.ZTEFCDriver
      san_ip = 10.1.2.3
      san_login = manage
      san_password = !manage

#. If HTTPS is not enabled in the array, include
   ``zte_api_protocol = http`` in each of the back-end definitions.

#. If HTTPS is enabled, you can enable certificate verification with the
   option ``zte_verify_certificate=True``. You may also use the
   ``zte_verify_certificate_path`` parameter to specify the path to a
   ``CA_BUNDLE`` file containing CAs other than those in the default list.

#. Modify the ``[DEFAULT]`` section of the ``cinder.conf`` file to add an
   ``enabled_backends`` parameter specifying the back-end entries you added,
   and a ``default_volume_type`` parameter specifying the name of a volume
   type that you will create in the next step.

   **Example: [DEFAULT] section changes**

   .. code-block:: ini

      [DEFAULT]
      # ...
      enabled_backends = pool-a,pool-b
      default_volume_type = zte

#. Create a new volume type for each distinct ``volume_backend_name`` value
   that you added to the ``cinder.conf`` file. The example below
   assumes that the same ``volume_backend_name=zte-array``
   option was specified in all of the
   entries, and specifies that the volume type ``zte`` can be used to
   allocate volumes from any of them.

   **Example: Creating a volume type**

   .. code-block:: console

      $ openstack volume type create zte
      $ openstack volume type set --property volume_backend_name=zte-array zte

#. After modifying the ``cinder.conf`` file,
   restart the ``cinder-volume`` service.

Driver-specific options
~~~~~~~~~~~~~~~~~~~~~~~

The following table contains the configuration options that are specific
to the ZTE drivers.

.. include:: ../../tables/cinder-zte.inc
