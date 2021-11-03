===========================
TOYOU NetStor Cinder driver
===========================

TOYOU NetStor series volume driver provides OpenStack Compute instances
with access to TOYOU NetStor series storage systems.

TOYOU NetStor storage can be used with iSCSI or FC connection.

This documentation explains how to configure and connect the block storage
nodes to TOYOU NetStor series storage.

Driver options
~~~~~~~~~~~~~~

The following table contains the configuration options supported by the
TOYOU NetStor iSCSI/FC driver.

.. config-table::
   :config-target: TOYOU NetStor

   cinder.volume.drivers.toyou.acs5000.acs5000_common

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, list, delete, attach (map), and detach (unmap) volumes.
- Create, list and delete volume snapshots.
- Create a volume from a snapshot.
- Copy an image to a volume.
- Copy a volume to an image.
- Clone a volume.
- Extend a volume.
- Migrate a volume.
- Manage/Unmanage volume.
- Revert to Snapshot.
- Multi-attach.
- Thin Provisioning.
- Extend Attached Volume.

Configure TOYOU NetStor iSCSI/FC backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section details the steps required to configure the TOYOU NetStor
storage cinder driver.

#. In the ``cinder.conf`` configuration file under the ``[DEFAULT]``
   section, set the enabled_backends parameter
   with the iSCSI or FC back-end group.

   -  For Fibre Channel:

      .. code-block:: ini

         [DEFAULT]
         enabled_backends = toyou-fc-1

   -  For iSCSI:

      .. code-block:: ini

         [DEFAULT]
         enabled_backends = toyou-iscsi-1


#. Add a backend group section for the backend group specified
   in the enabled_backends parameter.

#. In the newly created backend group section, set the
   following configuration options:

   -  For Fibre Channel:

      .. code-block:: ini

         [toyou-fc-1]
         # The TOYOU NetStor driver path
         volume_driver = cinder.volume.drivers.toyou.acs5000.acs5000_fc.Acs5000FCDriver
         # Management IP of TOYOU NetStor storage array
         san_ip = 10.0.0.10
         # Management username of TOYOU NetStor storage array
         san_login = cliuser
         # Management password of TOYOU NetStor storage array
         san_password = clipassword
         # The Pool used to allocated volumes
         acs5000_volpool_name = pool01
         # Backend name
         volume_backend_name = toyou-fc

   -  For iSCSI:

      .. code-block:: ini

         [toyou-iscsi-1]
         # The TOYOU NetStor driver path
         volume_driver = cinder.volume.drivers.toyou.acs5000.acs5000_iscsi.Acs5000ISCSIDriver
         # Management IP of TOYOU NetStor storage array
         san_ip = 10.0.0.10
         # Management username of TOYOU NetStor storage array
         san_login = cliuser
         # Management password of TOYOU NetStor storage array
         san_password = clipassword
         # The Pool used to allocated volumes
         acs5000_volpool_name = pool01
         # Backend name
         volume_backend_name = toyou-iscsi
