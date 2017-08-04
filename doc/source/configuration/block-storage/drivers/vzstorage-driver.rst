========================
Virtuozzo Storage driver
========================

The Virtuozzo Storage driver is a fault-tolerant distributed storage
system that is optimized for virtualization workloads.
Set the following in your ``cinder.conf`` file, and use the following
options to configure it.

.. code-block:: ini

   volume_driver = cinder.volume.drivers.vzstorage.VZStorageDriver

.. include:: ../../tables/cinder-vzstorage.inc
