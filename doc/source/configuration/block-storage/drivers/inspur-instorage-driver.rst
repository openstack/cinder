=====================================
Inspur InStorage family volume driver
=====================================

Inspur InStorage family volume driver provides OpenStack Compute instances
with access to Inspur Instorage family storage system.

Inspur InStorage storage system can be used with FC or iSCSI connection.

This documentation explains how to configure and connect the block storage
nodes to Inspur InStorage family storage system.

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, list, delete, attach (map), and detach (unmap) volumes.
- Create, list and delete volume snapshots.
- Create a volume from a snapshot.
- Copy an image to a volume.
- Copy a volume to an image.
- Clone a volume.
- Extend a volume.
- Retype a volume.
- Manage and unmanage a volume.
- Create, list, and delete consistency group.
- Create, list, and delete consistency group snapshot.
- Modify consistency group (add or remove volumes).
- Create consistency group from source.
- Failover and Failback support.

Configure Inspur InStorage iSCSI/FC backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section details the steps required to configure the Inspur InStorage
Cinder Driver for single FC or iSCSI backend.

#. In the ``cinder.conf`` configuration file under the ``[DEFAULT]``
   section, set the enabled_backends parameter
   with the iSCSI or FC back-end group

   -  For Fibre Channel:

      .. code-block:: ini

         [DEFAULT]
         enabled_backends = instorage-fc-1

   -  For iSCSI:

      .. code-block:: ini

         [DEFAULT]
         enabled_backends = instorage-iscsi-1


#. Add a back-end group section for back-end group specified
   in the enabled_backends parameter

#. In the newly created back-end group section, set the
   following configuration options:

   -  For Fibre Channel:

      .. code-block:: ini

         [instorage-fc-1]
         # Management IP of Inspur InStorage storage array
         san_ip = 10.0.0.10
         # Management Port of Inspur InStorage storage array, by default set to 22
         san_ssh_port = 22
         # Management username of Inspur InStorage storage array
         san_login = username
         # Management password of Inspur InStorage storage array
         san_password = password
         # Private key for Inspur InStorage storage array
         san_private_key = path/to/the/private/key
         # The Pool used to allocated volumes
         instorage_mcs_volpool_name = Pool0
         # The driver path
         volume_driver = cinder.volume.drivers.inspur.instorage.instorage_fc.InStorageMCSFCDriver
         # Backend name
         volume_backend_name = instorage_fc

   -  For iSCSI:

      .. code-block:: ini

         [instorage-iscsi-1]
         # Management IP of Inspur InStorage storage array
         san_ip = 10.0.0.10
         # Management Port of Inspur InStorage storage array, by default set to 22
         san_ssh_port = 22
         # Management username of Inspur InStorage storage array
         san_login = username
         # Management password of Inspur InStorage storage array
         san_password = password
         # Private key for Inspur InStorage storage array
         san_private_key = path/to/the/private/key
         # The Pool used to allocated volumes
         instorage_mcs_volpool_name = Pool0
         # The driver path
         volume_driver = cinder.volume.drivers.inspur.instorage.instorage_iscsi.InStorageMCSISCSIDriver
         # Backend name
         volume_backend_name = instorage_iscsi

   .. note::
      When both ``san_password`` and ``san_private_key`` are provide, the driver will use private key prefer to password.


#. Save the changes to the ``/etc/cinder/cinder.conf`` file and
   restart the ``cinder-volume`` service.
