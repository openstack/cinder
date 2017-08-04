=======================
GlusterFS backup driver
=======================

The GlusterFS backup driver backs up volumes of any type to GlusterFS.

To enable the GlusterFS backup driver, include the following option in the
``cinder.conf`` file:

.. code-block:: ini

    backup_driver = cinder.backup.drivers.glusterfs

The following configuration options are available for the GlusterFS backup
driver.

.. include:: ../../tables/cinder-backups_glusterfs.inc
