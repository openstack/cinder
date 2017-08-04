==============
SambaFS driver
==============

There is a volume back-end for Samba filesystems. Set the following in
your ``cinder.conf`` file, and use the following options to configure it.

.. note::

   The SambaFS driver requires ``qemu-img`` version 1.7 or higher on Linux
   nodes, and ``qemu-img`` version 1.6 or higher on Windows nodes.

.. code-block:: ini

   volume_driver = cinder.volume.drivers.smbfs.SmbfsDriver

.. include:: ../../tables/cinder-smbfs.inc
