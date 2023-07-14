================================
TOYOU NetStor TYDS Cinder driver
================================

TOYOU NetStor TYDS series volume driver provides OpenStack Compute instances
with access to TOYOU NetStor TYDS series storage systems.

TOYOU NetStor TYDS storage can be used with iSCSI connection.

This documentation explains how to configure and connect the block storage
nodes to TOYOU NetStor TYDS series storage.

Driver options
~~~~~~~~~~~~~~

The following table contains the configuration options supported by the
TOYOU NetStor TYDS iSCSI driver.

.. config-table::
   :config-target: TOYOU NetStor TYDS

   cinder.volume.drivers.toyou.tyds.tyds

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create Volume.
- Delete Volume.
- Attach Volume.
- Detach Volume.
- Extend Volume
- Create Snapshot.
- Delete Snapshot.
- Create Volume from Snapshot.
- Create Volume from Volume (clone).
- Create lmage from Volume.
- Volume Migration (host assisted).

Configure TOYOU NetStor TOYOU TYDS iSCSI backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section details the steps required to configure the TOYOU NetStor
TYDS storage cinder driver.

#. In the ``cinder.conf`` configuration file under the ``[DEFAULT]``
   section, set the enabled_backends parameter
   with the iSCSI back-end group.

   .. code-block:: ini

      [DEFAULT]
      enabled_backends = toyou-tyds-iscsi-1


#. Add a backend group section for the backend group specified
   in the enabled_backends parameter.

#. In the newly created backend group section, set the
   following configuration options:

   .. code-block:: ini

      [toyou-tyds-iscsi-1]
      # The TOYOU NetStor TYDS driver path
      volume_driver = cinder.volume.drivers.toyou.tyds.tyds.TYDSDriver
      # Management http ip of TOYOU NetStor TYDS storage
      san_ip = 10.0.0.10
      # Management http username of TOYOU NetStor TYDS storage
      san_login = superuser
      # Management http password of TOYOU NetStor TYDS storage
      san_password = Toyou@123
      # The Pool used to allocated volumes
      tyds_pools = pool01
      # Backend name
      volume_backend_name = toyou-tyds-iscsi-1
