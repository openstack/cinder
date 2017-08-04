============================
Nimble Storage volume driver
============================

Nimble Storage fully integrates with the OpenStack platform through
the Nimble Cinder driver, allowing a host to configure and manage Nimble
Storage array features through Block Storage interfaces.

Support for iSCSI storage protocol is available with NimbleISCSIDriver
Volume Driver class and Fibre Channel with NimbleFCDriver.

Support for the Liberty release and above is available from Nimble OS
2.3.8 or later.

Supported operations
~~~~~~~~~~~~~~~~~~~~

* Create, delete, clone, attach, and detach volumes
* Create and delete volume snapshots
* Create a volume from a snapshot
* Copy an image to a volume
* Copy a volume to an image
* Extend a volume
* Get volume statistics
* Manage and unmanage a volume
* Enable encryption and default performance policy for a volume-type
  extra-specs
* Force backup of an in-use volume.

Nimble Storage driver configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Update the file ``/etc/cinder/cinder.conf`` with the given configuration.

In case of a basic (single back-end) configuration, add the parameters
within the ``[default]`` section as follows.

.. code-block:: ini

   [default]
   san_ip = NIMBLE_MGMT_IP
   san_login = NIMBLE_USER
   san_password = NIMBLE_PASSWORD
   use_multipath_for_image_xfer = True
   volume_driver = NIMBLE_VOLUME_DRIVER

In case of multiple back-end configuration, for example, configuration
which supports multiple Nimble Storage arrays or a single Nimble Storage
array with arrays from other vendors, use the following parameters.

.. code-block:: ini

   [default]
   enabled_backends = Nimble-Cinder

   [Nimble-Cinder]
   san_ip = NIMBLE_MGMT_IP
   san_login = NIMBLE_USER
   san_password = NIMBLE_PASSWORD
   use_multipath_for_image_xfer = True
   volume_driver = NIMBLE_VOLUME_DRIVER
   volume_backend_name = NIMBLE_BACKEND_NAME

In case of multiple back-end configuration, Nimble Storage volume type
is created and associated with a back-end name as follows.

.. note::

   Single back-end configuration users do not need to create the volume type.

.. code-block:: console

   $ openstack volume type create NIMBLE_VOLUME_TYPE
   $ openstack volume type set --property volume_backend_name=NIMBLE_BACKEND_NAME NIMBLE_VOLUME_TYPE

This section explains the variables used above:

NIMBLE_MGMT_IP
  Management IP address of Nimble Storage array/group.

NIMBLE_USER
  Nimble Storage account login with minimum ``power user`` (admin) privilege
  if RBAC is used.

NIMBLE_PASSWORD
  Password of the admin account for nimble array.

NIMBLE_VOLUME_DRIVER
  Use either cinder.volume.drivers.nimble.NimbleISCSIDriver for iSCSI or
  cinder.volume.drivers.nimble.NimbleFCDriver for Fibre Channel.

NIMBLE_BACKEND_NAME
  A volume back-end name which is specified in the ``cinder.conf`` file.
  This is also used while assigning a back-end name to the Nimble volume type.

NIMBLE_VOLUME_TYPE
  The Nimble volume-type which is created from the CLI and associated with
  ``NIMBLE_BACKEND_NAME``.

  .. note::

     Restart the ``cinder-api``, ``cinder-scheduler``, and ``cinder-volume``
     services after updating the ``cinder.conf`` file.

Nimble driver extra spec options
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Nimble volume driver also supports the following extra spec options:

'nimble:encryption'='yes'
  Used to enable encryption for a volume-type.

'nimble:perfpol-name'=PERF_POL_NAME
  PERF_POL_NAME is the name of a performance policy which exists on the
  Nimble array and should be enabled for every volume in a volume type.

'nimble:multi-initiator'='true'
  Used to enable multi-initiator access for a volume-type.

These extra-specs can be enabled by using the following command:

.. code-block:: console

   $ openstack volume type set --property KEY=VALUE VOLUME_TYPE

``VOLUME_TYPE`` is the Nimble volume type and ``KEY`` and ``VALUE`` are
the options mentioned above.

Configuration options
~~~~~~~~~~~~~~~~~~~~~

The Nimble storage driver supports these configuration options:

.. include:: ../../tables/cinder-nimble.inc
