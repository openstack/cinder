==============
Volume drivers
==============

To use different volume drivers for the cinder-volume service, use the
parameters described in these sections.

These volume drivers are included in the `Block Storage repository
<https://opendev.org/openstack/cinder>`_. To set a volume
driver, use the ``volume_driver`` flag.

The default is:

.. code-block:: ini

    volume_driver = cinder.volume.drivers.lvm.LVMVolumeDriver

Note that some third party storage systems may maintain more detailed
configuration documentation elsewhere. Contact your vendor for more information
if needed.

Driver Configuration Reference
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. sort by the drivers by open source software
.. and the drivers for proprietary components

.. toctree::
   :glob:
   :maxdepth: 1

   drivers/ceph-rbd-volume-driver
   drivers/lvm-volume-driver
   drivers/nfs-volume-driver
   drivers/*
