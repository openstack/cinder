===============
Sheepdog driver
===============

Sheepdog is an open-source distributed storage system that provides a
virtual storage pool utilizing internal disk of commodity servers.

Sheepdog scales to several hundred nodes, and has powerful virtual disk
management features like snapshotting, cloning, rollback, and thin
provisioning.

More information can be found on `Sheepdog
Project <http://sheepdog.github.io/sheepdog/>`__.

This driver enables the use of Sheepdog through Qemu/KVM.

Supported operations
~~~~~~~~~~~~~~~~~~~~

Sheepdog driver supports these operations:

- Create, delete, attach, and detach volumes.

- Create, list, and delete volume snapshots.

- Create a volume from a snapshot.

- Copy an image to a volume.

- Copy a volume to an image.

- Clone a volume.

- Extend a volume.

Configuration
~~~~~~~~~~~~~

Set the following option in the ``cinder.conf`` file:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.sheepdog.SheepdogDriver

The following table contains the configuration options supported by the
Sheepdog driver:

.. include:: ../../tables/cinder-sheepdog.inc
