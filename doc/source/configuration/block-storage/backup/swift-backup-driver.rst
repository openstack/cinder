===================
Swift backup driver
===================

The backup driver for the swift back end performs a volume backup to an
object storage system.

To enable the swift backup driver, include the following option in the
``cinder.conf`` file:

.. code-block:: ini

    backup_driver = cinder.backup.drivers.swift

The following configuration options are available for the Swift back-end
backup driver.

.. include:: ../../tables/cinder-backups_swift.inc

To enable the swift backup driver for 1.0, 2.0, or 3.0  authentication version,
specify ``1``, ``2``, or ``3`` correspondingly. For example:

.. code-block:: ini

    backup_swift_auth_version = 2

In addition, the 2.0 authentication system requires the definition of the
``backup_swift_tenant`` setting:

.. code-block:: ini

    backup_swift_tenant = <None>

This example shows the default options for the Swift back-end backup
driver.

.. code-block:: ini

    backup_swift_url = http://localhost:8080/v1/AUTH_
    backup_swift_auth_url = http://localhost:5000/v3
    backup_swift_auth = per_user
    backup_swift_auth_version = 1
    backup_swift_user = <None>
    backup_swift_user_domain = <None>
    backup_swift_key = <None>
    backup_swift_container = volumebackups
    backup_swift_object_size = 52428800
    backup_swift_project = <None>
    backup_swift_project_domain = <None>
    backup_swift_retry_attempts = 3
    backup_swift_retry_backoff = 2
    backup_compression_algorithm = zlib
