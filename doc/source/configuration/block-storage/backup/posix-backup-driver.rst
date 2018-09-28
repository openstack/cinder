================================
POSIX file systems backup driver
================================

The POSIX file systems backup driver backs up volumes of any type to
POSIX file systems.

To enable the POSIX file systems backup driver, include the following
option in the ``cinder.conf`` file:

.. code-block:: ini

    backup_driver = cinder.backup.drivers.posix.PosixBackupDriver

The following configuration options are available for the POSIX
file systems backup driver.

.. config-table::
   :config-target: POSIX backup driver

   cinder.backup.drivers.posix
