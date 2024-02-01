==========================
Dell PowerStore driver
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
- Quality of Service (QoS)
- Cinder volume active/active support.

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

Driver configuration to use NVMe-OF
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

NVMe-OF support was added in PowerStore starting from version 2.1.

.. note:: Currently the driver supports only NVMe over TCP.

To configure NVMe-OF driver add the following
content into ``/etc/cinder/cinder.conf``:

.. code-block:: ini

  [DEFAULT]
  enabled_backends = powerstore

  [powerstore]
  # PowerStore REST IP
  san_ip = <San IP>
  # PowerStore REST username and password
  san_login = <San username>
  san_password = <San Password>
  # Volume driver name
  volume_driver = cinder.volume.drivers.dell_emc.powerstore.driver.PowerStoreDriver
  # Backend name
  volume_backend_name = <Backend name>
  powerstore_nvme = True

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

Image Volume Caching support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The image volume cache functionality is supported.
To enable it, modify the following options in the
``cinder.conf`` file:

.. code-block:: ini

  image_volume_cache_enabled = True

By default, Image Volume Caching is disabled.


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

QoS (Quality of Service) support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. note:: QoS is supported in PowerStore version 4.0 or later.

The PowerStore driver supports Quality of Service (QoS) by
enabling the following capabilities:

``bandwidth_limit_type``
    The QoS bandwidth limit type. This type setting determines
    how the max_iops and max_bw attributes are used.
    This has the following two values:

    1. ``Absolute`` - Limits are absolute values specified,
    either I/O operations per second or bandwidth.

    2. ``Density`` -  Limits specified are per GB,
    e.g. I/O operations per second per GB.

.. note:: This (bandwidth_limit_type) property is mandatory when creating QoS.

``max_iops``
    Maximum I/O operations in either I/O operations per second (IOPS) or
    I/O operations per second per GB. The specification of the type
    attribute determines which metric is used.
    If type is set to absolute, max_iops is specified in IOPS.
    If type is set to density, max_iops is specified in IOPS per GB.
    If both max_iops and max_bw are specified,
    the system will limit I/O if either value is exceeded.
    The value must be within the range of 1 to 2147483646.

``max_bw``
    Maximum I/O bandwidth measured in either Kilobytes per second or Kilobytes
    per second / per GB. The specification of the type attribute determines
    which measurement is used. If type is set to absolute, max_bw is specified
    in Kilobytes per second. If type is set to density max_bw is specified
    in Kilobytes per second / per GB.
    If both max_iops and max_bw are specified, the system will
    limit I/O if either value is exceeded.
    The value must be within the range of 2000 to 2147483646.

``burst_percentage``
    Percentage indicating by how much the limit may be exceeded. If I/O
    normally runs below the specified limit, then the volume or volume_group
    will accumulate burst credits that can be used to exceed the limit for
    a short period (a few seconds, but will not exceed the burst limit).
    This burst percentage applies to both max_iops and max_bw and
    is independent of the type setting.
    The value must be within the range of 0 to 100.
    If this property is not specified during QoS creation,
    a default value of 0 will be used.

.. note:: When creating QoS, you must define either ``max_iops`` or ``max_bw``, or you can define both.

.. code-block:: console

    $ openstack volume qos create --consumer back-end --property max_iops=100 --property max_bw=50000 --property bandwidth_limit_type=Absolute --property burst_percentage=80 powerstore_qos
    $ openstack volume type create --property volume_backend_name=powerstore powerstore
    $ openstack volume qos associate powerstore_qos powerstore

.. note:: There are two approaches for updating QoS properties in PowerStore:

    #. ``Retype the Volume``:
        This involves retyping the volume with the different QoS settings and migrating the volume to the new type.
    #. ``Modify Existing QoS Properties`` (Recommended):
        This method entails changing the existing QoS properties and creating a new instance or image
        volume to update the QoS policy in PowerStore. This will also update the QoS properties of existing attached volumes,
        created with the same volume type.
