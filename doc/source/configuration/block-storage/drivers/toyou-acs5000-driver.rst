==========================
TOYOU ACS5000 iSCSI driver
==========================

TOYOU ACS5000 series volume driver provides OpenStack Compute instances
with access to TOYOU ACS5000 series storage systems.

TOYOU ACS5000 storage can be used with iSCSI connection.

This documentation explains how to configure and connect the block storage
nodes to TOYOU ACS5000 series storage.

Driver options
~~~~~~~~~~~~~~

The following table contains the configuration options supported by the
TOYOU ACS5000 iSCSI driver.

.. config-table::
   :config-target: TOYOU ACS5000

   cinder.volume.drivers.toyou.acs5000.acs5000_iscsi
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

Configure TOYOU ACS5000 iSCSI backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section details the steps required to configure the TOYOU ACS5000
storage cinder driver.

#. In the ``cinder.conf`` configuration file under the ``[DEFAULT]``
   section, set the enabled_backends parameter.

   .. code-block:: ini

       [DEFAULT]
       enabled_backends = ACS5000-1


#. Add a backend group section for the backend group specified
   in the enabled_backends parameter.

#. In the newly created backend group section, set the
   following configuration options:

   .. code-block:: ini

       [ACS5000-1]
       # The driver path
       volume_driver = cinder.volume.drivers.toyou.acs5000.acs5000_iscsi.Acs5000ISCSIDriver
       # Management IP of TOYOU ACS5000 storage array
       san_ip = 10.0.0.10
       # Management username of TOYOU ACS5000 storage array
       san_login = cliuser
       # Management password of TOYOU ACS5000 storage array
       san_password = clipassword
       # The Pool used to allocated volumes
       acs5000_volpool_name = pool01
       # Backend name
       volume_backend_name = ACS5000
