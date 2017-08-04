========================================
IBM Tivoli Storage Manager backup driver
========================================

The IBM Tivoli Storage Manager (TSM) backup driver enables performing
volume backups to a TSM server.

The TSM client should be installed and configured on the machine running
the cinder-backup service. See the IBM Tivoli Storage Manager
Backup-Archive Client Installation and User's Guide for details on
installing the TSM client.

To enable the IBM TSM backup driver, include the following option in
``cinder.conf``:

.. code-block:: ini

    backup_driver = cinder.backup.drivers.tsm

The following configuration options are available for the TSM backup
driver.

.. include:: ../../tables/cinder-backups_tsm.inc

This example shows the default options for the TSM backup driver.

.. code-block:: ini

    backup_tsm_volume_prefix = backup
    backup_tsm_password = password
    backup_tsm_compression = True
