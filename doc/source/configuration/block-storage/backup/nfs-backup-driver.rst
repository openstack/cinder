=================
NFS backup driver
=================

The backup driver for the NFS back end backs up volumes of any type to
an NFS exported backup repository.

To enable the NFS backup driver, include the following option in the
``[DEFAULT]`` section of the ``cinder.conf`` file:

.. code-block:: ini

    backup_driver = cinder.backup.drivers.nfs

The following configuration options are available for the NFS back-end
backup driver.

.. include:: ../../tables/cinder-backups_nfs.inc
