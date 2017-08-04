=============================
Dell EqualLogic volume driver
=============================

The Dell EqualLogic volume driver interacts with configured EqualLogic
arrays and supports various operations.

Supported operations
~~~~~~~~~~~~~~~~~~~~

-  Create, delete, attach, and detach volumes.
-  Create, list, and delete volume snapshots.
-  Clone a volume.

Configuration
~~~~~~~~~~~~~

The OpenStack Block Storage service supports:

-  Multiple instances of Dell EqualLogic Groups or Dell EqualLogic Group
   Storage Pools and multiple pools on a single array.

-  Multiple instances of Dell EqualLogic Groups or Dell EqualLogic Group
   Storage Pools or multiple pools on a single array.

The Dell EqualLogic volume driver's ability to access the EqualLogic Group is
dependent upon the generic block storage driver's SSH settings in the
``/etc/cinder/cinder.conf`` file (see
:ref:`block-storage-sample-configuration-file` for reference).

.. include:: ../../tables/cinder-eqlx.inc

Default (single-instance) configuration
---------------------------------------

The following sample ``/etc/cinder/cinder.conf`` configuration lists the
relevant settings for a typical Block Storage service using a single
Dell EqualLogic Group:

.. code-block:: ini

   [DEFAULT]
   # Required settings

   volume_driver = cinder.volume.drivers.dell_emc.ps.PSSeriesISCSIDriver
   san_ip = IP_EQLX
   san_login = SAN_UNAME
   san_password = SAN_PW
   eqlx_group_name = EQLX_GROUP
   eqlx_pool = EQLX_POOL

   # Optional settings

   san_thin_provision = true|false
   use_chap_auth = true|false
   chap_username = EQLX_UNAME
   chap_password = EQLX_PW
   eqlx_cli_max_retries = 5
   san_ssh_port = 22
   ssh_conn_timeout = 30
   san_private_key = SAN_KEY_PATH
   ssh_min_pool_conn = 1
   ssh_max_pool_conn = 5

In this example, replace the following variables accordingly:

IP_EQLX
    The IP address used to reach the Dell EqualLogic Group through SSH.
    This field has no default value.

SAN_UNAME
    The user name to login to the Group manager via SSH at the
    ``san_ip``. Default user name is ``grpadmin``.

SAN_PW
    The corresponding password of SAN_UNAME. Not used when
    ``san_private_key`` is set. Default password is ``password``.

EQLX_GROUP
    The group to be used for a pool where the Block Storage service will
    create volumes and snapshots. Default group is ``group-0``.

EQLX_POOL
    The pool where the Block Storage service will create volumes and
    snapshots. Default pool is ``default``. This option cannot be used
    for multiple pools utilized by the Block Storage service on a single
    Dell EqualLogic Group.

EQLX_UNAME
    The CHAP login account for each volume in a pool, if
    ``use_chap_auth`` is set to ``true``. Default account name is
    ``chapadmin``.

EQLX_PW
    The corresponding password of EQLX_UNAME. The default password is
    randomly generated in hexadecimal, so you must set this password
    manually.

SAN_KEY_PATH (optional)
    The filename of the private key used for SSH authentication. This
    provides password-less login to the EqualLogic Group. Not used when
    ``san_password`` is set. There is no default value.

In addition, enable thin provisioning for SAN volumes using the default
``san_thin_provision = true`` setting.

Multiple back-end configuration
-------------------------------

The following example shows the typical configuration for a Block
Storage service that uses two Dell EqualLogic back ends:

.. code-block:: ini

   enabled_backends = backend1,backend2
   san_ssh_port = 22
   ssh_conn_timeout = 30
   san_thin_provision = true

   [backend1]
   volume_driver = cinder.volume.drivers.dell_emc.ps.PSSeriesISCSIDriver
   volume_backend_name = backend1
   san_ip = IP_EQLX1
   san_login = SAN_UNAME
   san_password = SAN_PW
   eqlx_group_name = EQLX_GROUP
   eqlx_pool = EQLX_POOL

   [backend2]
   volume_driver = cinder.volume.drivers.dell_emc.ps.PSSeriesISCSIDriver
   volume_backend_name = backend2
   san_ip = IP_EQLX2
   san_login = SAN_UNAME
   san_password = SAN_PW
   eqlx_group_name = EQLX_GROUP
   eqlx_pool = EQLX_POOL

In this example:

-  Thin provisioning for SAN volumes is enabled
   (``san_thin_provision = true``). This is recommended when setting up
   Dell EqualLogic back ends.

-  Each Dell EqualLogic back-end configuration (``[backend1]`` and
   ``[backend2]``) has the same required settings as a single back-end
   configuration, with the addition of ``volume_backend_name``.

-  The ``san_ssh_port`` option is set to its default value, 22. This
   option sets the port used for SSH.

-  The ``ssh_conn_timeout`` option is also set to its default value, 30.
   This option sets the timeout in seconds for CLI commands over SSH.

-  The ``IP_EQLX1`` and ``IP_EQLX2`` refer to the IP addresses used to
   reach the Dell EqualLogic Group of ``backend1`` and ``backend2``
   through SSH, respectively.

For information on configuring multiple back ends, see `Configure a
multiple-storage back
end <https://docs.openstack.org/admin-guide/blockstorage-multi-backend.html>`__.
