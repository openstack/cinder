========================
S3 Storage backup driver
========================

The S3 backup driver backs up volumes to any type of Amazon S3
and S3 compatible object storages.

To enable the S3 backup driver, include the following option
in the ``cinder.conf`` file:

.. code-block:: ini

    backup_driver = cinder.backup.drivers.s3.S3BackupDriver

The following configuration options are available for the S3 backup driver.

.. config-table::
   :config-target: S3 backup driver

   cinder.backup.drivers.s3
