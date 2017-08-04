===================
Scality SOFS driver
===================

The Scality SOFS volume driver interacts with configured sfused mounts.

The Scality SOFS driver manages volumes as sparse files stored on a
Scality Ring through sfused. Ring connection settings and sfused options
are defined in the ``cinder.conf`` file and the configuration file
pointed to by the ``scality_sofs_config`` option, typically
``/etc/sfused.conf``.

Supported operations
~~~~~~~~~~~~~~~~~~~~

The Scality SOFS volume driver provides the following Block Storage
volume operations:

- Create, delete, attach (map), and detach (unmap) volumes.

- Create, list, and delete volume snapshots.

- Create a volume from a snapshot.

- Copy an image to a volume.

- Copy a volume to an image.

- Clone a volume.

- Extend a volume.

- Backup a volume.

- Restore backup to new or existing volume.

Configuration
~~~~~~~~~~~~~

Use the following instructions to update the ``cinder.conf``
configuration file:

.. code-block:: ini

   [DEFAULT]
   enabled_backends = scality-1

   [scality-1]
   volume_driver = cinder.volume.drivers.scality.ScalityDriver
   volume_backend_name = scality-1

   scality_sofs_config = /etc/sfused.conf
   scality_sofs_mount_point = /cinder
   scality_sofs_volume_dir = cinder/volumes

Compute configuration
~~~~~~~~~~~~~~~~~~~~~

Use the following instructions to update the ``nova.conf`` configuration
file:

.. code-block:: ini

   [libvirt]
   scality_sofs_mount_point = /cinder
   scality_sofs_config = /etc/sfused.conf

.. include:: ../../tables/cinder-scality.inc
