===================================================
Pure Storage iSCSI and Fibre Channel volume drivers
===================================================

The Pure Storage FlashArray volume drivers for OpenStack Block Storage
interact with configured Pure Storage arrays and support various
operations.

Support for iSCSI storage protocol is available with the PureISCSIDriver
Volume Driver class, and Fibre Channel with PureFCDriver.

All drivers are compatible with Purity FlashArrays that support the REST
API version 1.2, 1.3, 1.4, or 1.5 (Purity 4.0.0 and newer).

Limitations and known issues
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you do not set up the nodes hosting instances to use multipathing,
all network connectivity will use a single physical port on the array.
In addition to significantly limiting the available bandwidth, this
means you do not have the high-availability and non-disruptive upgrade
benefits provided by FlashArray. Multipathing must be used to take advantage
of these benefits.

Supported operations
~~~~~~~~~~~~~~~~~~~~

* Create, delete, attach, detach, retype, clone, and extend volumes.

* Create a volume from snapshot.

* Create, list, and delete volume snapshots.

* Create, list, update, and delete consistency groups.

* Create, list, and delete consistency group snapshots.

* Manage and unmanage a volume.

* Manage and unmanage a snapshot.

* Get volume statistics.

* Create a thin provisioned volume.

* Replicate volumes to remote Pure Storage array(s).

Configure OpenStack and Purity
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You need to configure both your Purity array and your OpenStack cluster.

.. note::

   These instructions assume that the ``cinder-api`` and ``cinder-scheduler``
   services are installed and configured in your OpenStack cluster.

Configure the OpenStack Block Storage service
---------------------------------------------

In these steps, you will edit the ``cinder.conf`` file to configure the
OpenStack Block Storage service to enable multipathing and to use the
Pure Storage FlashArray as back-end storage.

#. Install Pure Storage PyPI module.
   A requirement for the Pure Storage driver is the installation of the
   Pure Storage Python SDK version 1.4.0 or later from PyPI.

   .. code-block:: console

      $ pip install purestorage

#. Retrieve an API token from Purity.
   The OpenStack Block Storage service configuration requires an API token
   from Purity. Actions performed by the volume driver use this token for
   authorization. Also, Purity logs the volume driver's actions as being
   performed by the user who owns this API token.

   If you created a Purity user account that is dedicated to managing your
   OpenStack Block Storage volumes, copy the API token from that user
   account.

   Use the appropriate create or list command below to display and copy the
   Purity API token:

   * To create a new API token:

     .. code-block:: console

        $ pureadmin create --api-token USER

     The following is an example output:

     .. code-block:: console

        $ pureadmin create --api-token pureuser
        Name      API Token                             Created
        pureuser  902fdca3-7e3f-d2e4-d6a6-24c2285fe1d9  2014-08-04 14:50:30

   * To list an existing API token:

     .. code-block:: console

        $ pureadmin list --api-token --expose USER

     The following is an example output:

     .. code-block:: console

        $ pureadmin list --api-token --expose pureuser
        Name      API Token                             Created
        pureuser  902fdca3-7e3f-d2e4-d6a6-24c2285fe1d9  2014-08-04 14:50:30

#. Copy the API token retrieved (``902fdca3-7e3f-d2e4-d6a6-24c2285fe1d9`` from
   the examples above) to use in the next step.

#. Edit the OpenStack Block Storage service configuration file.
   The following sample ``/etc/cinder/cinder.conf`` configuration lists the
   relevant settings for a typical Block Storage service using a single
   Pure Storage array:

   .. code-block:: ini

      [DEFAULT]
      enabled_backends = puredriver-1
      default_volume_type = puredriver-1

      [puredriver-1]
      volume_backend_name = puredriver-1
      volume_driver = PURE_VOLUME_DRIVER
      san_ip = IP_PURE_MGMT
      pure_api_token = PURE_API_TOKEN
      use_multipath_for_image_xfer = True

   Replace the following variables accordingly:

   PURE_VOLUME_DRIVER
       Use either ``cinder.volume.drivers.pure.PureISCSIDriver`` for iSCSI or
       ``cinder.volume.drivers.pure.PureFCDriver`` for Fibre Channel
       connectivity.

   IP_PURE_MGMT
       The IP address of the Pure Storage array's management interface or a
       domain name that resolves to that IP address.

   PURE_API_TOKEN
       The Purity Authorization token that the volume driver uses to
       perform volume management on the Pure Storage array.

.. note::

   The volume driver automatically creates Purity host objects for
   initiators as needed. If CHAP authentication is enabled via the
   ``use_chap_auth`` setting, you must ensure there are no manually
   created host objects with IQN's that will be used by the OpenStack
   Block Storage service. The driver will only modify credentials on hosts that
   it manages.

.. note::

   If using the PureFCDriver it is recommended to use the OpenStack
   Block Storage Fibre Channel Zone Manager.

Volume auto-eradication
~~~~~~~~~~~~~~~~~~~~~~~

To enable auto-eradication of deleted volumes, snapshots, and consistency
groups on deletion, modify the following option in the ``cinder.conf`` file:

.. code-block:: ini

   pure_eradicate_on_delete = true

By default, auto-eradication is disabled and all deleted volumes, snapshots,
and consistency groups are retained on the Pure Storage array in a recoverable
state for 24 hours from time of deletion.

SSL certification
~~~~~~~~~~~~~~~~~

To enable SSL certificate validation, modify the following option in the
``cinder.conf`` file:

.. code-block:: ini

    driver_ssl_cert_verify = true

By default, SSL certificate validation is disabled.

To specify a non-default path to ``CA_Bundle`` file or directory with
certificates of trusted CAs:


.. code-block:: ini

    driver_ssl_cert_path = Certificate path

.. note::

   This requires the use of Pure Storage Python SDK > 1.4.0.

Replication configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

Add the following to the back-end specification to specify another Flash
Array to replicate to:

.. code-block:: ini

    [puredriver-1]
    replication_device = backend_id:PURE2_NAME,san_ip:IP_PURE2_MGMT,api_token:PURE2_API_TOKEN

Where ``PURE2_NAME`` is the name of the remote Pure Storage system,
``IP_PURE2_MGMT`` is the management IP address of the remote array,
and ``PURE2_API_TOKEN`` is the Purity Authorization token
of the remote array.

Note that more than one ``replication_device`` line can be added to allow for
multi-target device replication.

A volume is only replicated if the volume is of a volume-type that has
the extra spec ``replication_enabled`` set to ``<is> True``.

To create a volume type that specifies replication to remote back ends:

.. code-block:: console

   $ openstack volume type create ReplicationType
   $ openstack volume type set --property replication_enabled='<is> True' ReplicationType

The following table contains the optional configuration parameters available
for replication configuration with the Pure Storage array.

==================================================== ============= ======
Option                                               Description   Default
==================================================== ============= ======
``pure_replica_interval_default``                    Snapshot
                                                     replication
                                                     interval in
                                                     seconds.      ``3600``
``pure_replica_retention_short_term_default``        Retain all
                                                     snapshots on
                                                     target for
                                                     this time
                                                     (in seconds). ``14400``
``pure_replica_retention_long_term_per_day_default`` Retain how
                                                     many
                                                     snapshots
                                                     for each
                                                     day.          ``3``
``pure_replica_retention_long_term_default``         Retain
                                                     snapshots
                                                     per day
                                                     on target
                                                     for this
                                                     time (in
                                                     days).         ``7``
==================================================== ============= ======


.. note::

   ``replication-failover`` is only supported from the primary array to any of the
   multiple secondary arrays, but subsequent ``replication-failover`` is only
   supported back to the original primary array.

Automatic thin-provisioning/oversubscription ratio
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To enable this feature where we calculate the array oversubscription ratio as
(total provisioned/actual used), add the following option in the
``cinder.conf`` file:

.. code-block:: ini

    [puredriver-1]
    pure_automatic_max_oversubscription_ratio = True

By default, this is disabled and we honor the hard-coded configuration option
``max_over_subscription_ratio``.

.. note::

   Arrays with very good data reduction rates (compression/data deduplication/thin provisioning)
   can get *very* large oversubscription rates applied.

Scheduling metrics
~~~~~~~~~~~~~~~~~~

A large number of metrics are reported by the volume driver which can be useful
in implementing more control over volume placement in multi-backend
environments using the driver filter and weighter methods.

Metrics reported include, but are not limited to:

.. code-block:: text

   total_capacity_gb
   free_capacity_gb
   provisioned_capacity
   total_volumes
   total_snapshots
   total_hosts
   total_pgroups
   writes_per_sec
   reads_per_sec
   input_per_sec
   output_per_sec
   usec_per_read_op
   usec_per_read_op
   queue_depth

.. note::

   All total metrics include non-OpenStack managed objects on the array.

In conjunction with QOS extra-specs, you can create very complex algorithms to
manage volume placement. More detailed documentation on this is available in
other external documentation.
