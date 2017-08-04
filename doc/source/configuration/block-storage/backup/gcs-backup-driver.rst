=======================================
Google Cloud Storage backup driver
=======================================

The Google Cloud Storage (GCS) backup driver backs up volumes of any type to
Google Cloud Storage.

To enable the GCS backup driver, include the following option in the
``cinder.conf`` file:

.. code-block:: ini

    backup_driver = cinder.backup.drivers.google

The following configuration options are available for the GCS backup
driver.

.. include:: ../../tables/cinder-backups_gcs.inc
