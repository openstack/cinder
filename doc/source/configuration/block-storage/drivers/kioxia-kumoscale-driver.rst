==============================
KIOXIA Kumoscale NVMeOF Driver
==============================

KIOXIA Kumoscale volume driver provides OpenStack Compute instances
with access to KIOXIA Kumoscale NVMeOF storage systems.

This documentation explains how to configure Cinder for use with the
KIOXIA Kumoscale storage backend system.

Driver options
~~~~~~~~~~~~~~

The following table contains the configuration options supported by the
KIOXIA Kumoscale NVMeOF driver.

.. config-table::
   :config-target: KIOXIA Kumoscale

   cinder.volume.drivers.kioxia.kumoscale

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, list, delete, attach and detach volumes
- Create, list and delete volume snapshots
- Create a volume from a snapshot
- Copy an image to a volume.
- Copy a volume to an image.
- Create volume from snapshot
- Clone a volume
- Extend a volume

Configure KIOXIA Kumoscale NVMeOF backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section details the steps required to configure the KIOXIA Kumoscale
storage cinder driver.

#. In the ``cinder.conf`` configuration file under the ``[DEFAULT]``
   section, set the enabled_backends parameter.

   .. code-block:: ini

       [DEFAULT]
       enabled_backends = kumoscale-1


#. Add a backend group section for the backend group specified
   in the enabled_backends parameter.

#. In the newly created backend group section, set the
   following configuration options:

   .. code-block:: ini

       [kumoscale-1]
       # Backend name
       volume_backend_name=kumoscale-1
       # The driver path
       volume_driver=cinder.volume.drivers.kioxia.kumoscale.KumoScaleBaseVolumeDriver
       # Kumoscale provisioner URL
       kioxia_url=https://70.0.0.13:30100
       # Kumoscale provisioner cert file
       kioxia_cafile=/etc/kioxia/ssdtoolbox.pem
       # Kumoscale provisioner token
       token=eyJhbGciOiJIUzI1NiJ9...
