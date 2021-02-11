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
- OpenStack replication v2.1 support.
- Create, delete, update Consistency Groups.
- Create, delete Consistency Groups snapshots.
- Clone a Consistency Group.
- Create a Consistency Group from a Consistency Group snapshot.

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

Replication support
~~~~~~~~~~~~~~~~~~~

Configure replication
^^^^^^^^^^^^^^^^^^^^^

#. Pair source and destination PowerStore systems.

#. Create Protection policy and Replication rule with desired RPO.

#. Enable replication in ``cinder.conf`` file.

   To enable replication feature for storage backend set ``replication_device``
   as below:

   .. code-block:: ini

     ...
     replication_device = backend_id:powerstore_repl_1,
                          san_ip: <Replication system San ip>,
                          san_login: <Replication system San username>,
                          san_password: <Replication system San password>

   * Only one replication device is supported for storage backend.

   * Replication device supports the same options as the main storage backend.

#. Create volume type for volumes with replication enabled.

   .. code-block:: console

     $ openstack volume type create powerstore_replicated
     $ openstack volume type set --property replication_enabled='<is> True' powerstore_replicated

#. Set Protection policy name for volume type.

   .. code-block:: console

     $ openstack volume type set --property powerstore:protection_policy=<protection policy name> \
         powerstore_replicated

Failover host
^^^^^^^^^^^^^

In the event of a disaster, or where there is a required downtime the
administrator can issue the failover host command:

.. code-block:: console

   $ cinder failover-host cinder_host@powerstore --backend_id powerstore_repl_1

After issuing Cinder failover-host command Cinder will switch to configured
replication device, however to get existing instances to use this target and
new paths to volumes it is necessary to first shelve Nova instances and then
unshelve them, this will effectively restart the Nova instance and
re-establish data paths between Nova instances and the volumes.

.. code-block:: console

   $ nova shelve <server>
   $ nova unshelve [--availability-zone <availability_zone>] <server>

If the primary system becomes available, the administrator can initiate
failback operation using ``--backend_id default``:

.. code-block:: console

   $ cinder failover-host cinder_host@powerstore --backend_id default

Consistency Groups support
~~~~~~~~~~~~~~~~~~~~~~~~~~

To use PowerStore Volume Groups create Group Type with consistent group
snapshot enabled.

.. code-block:: console

  $ cinder --os-volume-api-version 3.11 group-type-create powerstore_vg
  $ cinder --os-volume-api-version 3.11 group-type-key powerstore_vg set consistent_group_snapshot_enabled="<is> True"

.. note:: Currently driver does not support Consistency Groups replication.
          Adding volume to Consistency Group and creating volume in Consistency Group
          will fail if volume is replicated.
