==========================
Dell EMC PowerStore driver
==========================

This section explains how to configure and connect the block
storage nodes to an PowerStore storage cluster.

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, delete, attach and detach volumes.
- Create, delete volume snapshots.
- Create a volume from a snapshot.
- Copy an image to a volume.
- Copy a volume to an image.
- Clone a volume.
- Extend a volume.
- Get volume statistics.
- Attach a volume to multiple servers simultaneously (multiattach).
- Revert a volume to a snapshot.

Driver configuration
~~~~~~~~~~~~~~~~~~~~

Add the following content into ``/etc/cinder/cinder.conf``:

.. code-block:: ini

  [DEFAULT]
  enabled_backends = powerstore

  [powerstore]
  # PowerStore REST IP
  san_ip = <San IP>
  # PowerStore REST username and password
  san_login = <San username>
  san_password = <San Password>
  # Storage protocol
  storage_protocol = <Storage protocol> # FC or iSCSI
  # Volume driver name
  volume_driver = cinder.volume.drivers.dell_emc.powerstore.driver.PowerStoreDriver
  # Backend name
  volume_backend_name = <Backend name>
  # PowerStore appliances
  powerstore_appliances = <Appliances names> # Ex. Appliance-1,Appliance-2
  # PowerStore allowed ports
  powerstore_ports = <Allowed ports> # Ex. 58:cc:f0:98:49:22:07:02,58:cc:f0:98:49:23:07:02

Driver options
~~~~~~~~~~~~~~

The driver supports the following configuration options:

.. config-table::
   :config-target: PowerStore

  cinder.volume.drivers.dell_emc.powerstore.driver

SSL support
~~~~~~~~~~~

To enable the SSL certificate verification, modify the following options in the
``cinder.conf`` file:

.. code-block:: ini

  driver_ssl_cert_verify = True
  driver_ssl_cert_path = <path to the CA>

By default, the SSL certificate validation is disabled.

If the ``driver_ssl_cert_path`` option is omitted, the system default CA will
be used.

Thin provisioning and compression
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The driver creates thin provisioned compressed volumes by default.
Thick provisioning is not supported.

CHAP authentication support
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The driver supports one-way (Single mode) CHAP authentication.
To use CHAP authentication CHAP Single mode has to be enabled on the storage
side.

.. note:: When enabling CHAP, any previously added hosts will need to be updated
          with CHAP configuration since there will be I/O disruption for those hosts.
          It is recommended that before adding hosts to the cluster,
          decide what type of CHAP configuration is required, if any.

CHAP configuration is retrieved from the storage during driver initialization,
no additional configuration is needed.
Secrets are generated automatically.
