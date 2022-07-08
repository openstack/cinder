==============================
Fungible Storage Driver
==============================

Fungible Storage volume driver provides OpenStack Compute instances
with access to Fungible Storage Cluster.

This documentation explains how to configure Cinder for use with the
Fungible Storage Cluster.

Driver requirements
~~~~~~~~~~~~~~~~~~~

- Fungible Storage Cluster

- FSC version >= 4.0

- nvme cli version >= v1.13

- The Block Storage Node should also have a data path to the
  Fungible Storage Cluster for the following operations:

  - Copy volume to image
  - Copy image to volume

Driver options
~~~~~~~~~~~~~~

The following table contains the configuration options supported by the
Fungible Storage driver.

.. config-table::
   :config-target: Fungible Storage Cluster

   cinder.volume.drivers.fungible.driver

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, list, delete, attach and detach volumes
- Create, list and delete volume snapshots
- Copy image to volume
- Copy volume to image
- Create volume from snapshot
- Clone volume
- Extend volume

Configure Fungible Storage Cluster backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section details the steps required to configure the
Fungible Storage cinder driver.

#. In the ``cinder.conf`` configuration file under the ``[DEFAULT]``
   section, set the enabled_backends parameter.

   .. code-block:: ini

       [DEFAULT]
       enabled_backends = fungible

#. Add a backend group section for the backend group specified
   in the enabled_backends parameter.

#. In the newly created backend group section, set the
   following configuration options:

   .. code-block:: ini

       [fungible]
       # Backend name
       volume_backend_name=fungible
       # The driver path
       volume_driver=cinder.volume.drivers.fungible.driver.FungibleDriver
       # Fungible composer details
       san_ip = <composer node VIP>
       san_login = <composer username>
       san_password = <composer password>
       # List below are optional
       nvme_connect_port = <nvme target endpoint port>
       api_enable_ssl = True/False
       iops_for_image_migration = <IOPS value>
