=====================================
Dell EMC ScaleIO Block Storage driver
=====================================

ScaleIO is a software-only solution that uses existing servers' local
disks and LAN to create a virtual SAN that has all of the benefits of
external storage, but at a fraction of the cost and complexity. Using the
driver, Block Storage hosts can connect to a ScaleIO Storage
cluster.

This section explains how to configure and connect the block storage
nodes to a ScaleIO storage cluster.

Support matrix
~~~~~~~~~~~~~~

.. list-table::
   :widths: 10 25
   :header-rows: 1

   * - ScaleIO version
     - Supported Linux operating systems
   * - 2.0
     - CentOS 6.x, CentOS 7.x, SLES 11 SP3, SLES 12, Ubuntu 14.04, Ubuntu 16.04

Deployment prerequisites
~~~~~~~~~~~~~~~~~~~~~~~~

* ScaleIO Gateway must be installed and accessible in the network.
  For installation steps, refer to the Preparing the installation Manager
  and the Gateway section in ScaleIO Deployment Guide. See
  :ref:`scale_io_docs`.

* ScaleIO Data Client (SDC) must be installed on all OpenStack nodes.

.. note:: Ubuntu users must follow the specific instructions in the ScaleIO
          deployment guide for Ubuntu environments. See the Deploying on
          Ubuntu servers section in ScaleIO Deployment Guide. See
          :ref:`scale_io_docs`.

.. _scale_io_docs:

Official documentation
----------------------

To find the ScaleIO documentation:

#. Go to the `ScaleIO product documentation page <https://support.emc.com/products/33925_ScaleIO/Documentation/?source=promotion>`_.

#. From the left-side panel, select the relevant version.

#. Search for "ScaleIO 2.0 Deployment Guide".

Supported operations
~~~~~~~~~~~~~~~~~~~~

* Create, delete, clone, attach, detach, manage, and unmanage volumes

* Create, delete, manage, and unmanage volume snapshots

* Create a volume from a snapshot

* Copy an image to a volume

* Copy a volume to an image

* Extend a volume

* Get volume statistics

* Create, list, update, and delete consistency groups

* Create, list, update, and delete consistency group snapshots

ScaleIO QoS support
~~~~~~~~~~~~~~~~~~~~

QoS support for the ScaleIO driver includes the ability to set the
following capabilities in the Block Storage API
``cinder.api.contrib.qos_specs_manage`` QoS specs extension module:

* ``maxIOPS``

* ``maxIOPSperGB``

* ``maxBWS``

* ``maxBWSperGB``

The QoS keys above must be created and associated with a volume type.
For information about how to set the key-value pairs and associate
them with a volume type, run the following commands:

.. code-block:: console

   $ openstack help volume qos

``maxIOPS``
 The QoS I/O rate limit. If not set, the I/O rate will be unlimited.
 The setting must be larger than 10.

``maxIOPSperGB``
 The QoS I/O rate limit.
 The limit will be calculated by the specified value multiplied by
 the volume size.
 The setting must be larger than 10.

``maxBWS``
 The QoS I/O bandwidth rate limit in KBs. If not set, the I/O
 bandwidth rate will be unlimited. The setting must be a multiple of 1024.

``maxBWSperGB``
 The QoS I/O bandwidth rate limit in KBs.
 The limit will be calculated by the specified value multiplied by
 the volume size.
 The setting must be a multiple of 1024.

The driver always chooses the minimum between the QoS keys value
and the relevant calculated value of ``maxIOPSperGB`` or ``maxBWSperGB``.

Since the limits are per SDC, they will be applied after the volume
is attached to an instance, and thus to a compute node/SDC.

ScaleIO thin provisioning support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Block Storage driver supports creation of thin-provisioned and
thick-provisioned volumes.
The provisioning type settings can be added as an extra specification
of the volume type, as follows:

.. code-block:: ini

   provisioning:type = thin\thick

The old specification: ``sio:provisioning_type`` is deprecated.

Oversubscription
----------------

Configure the oversubscription ratio by adding the following parameter
under the separate section for ScaleIO:

.. code-block:: ini

   sio_max_over_subscription_ratio = OVER_SUBSCRIPTION_RATIO

.. note::

   The default value for ``sio_max_over_subscription_ratio``
   is 10.0.

Oversubscription is calculated correctly by the Block Storage service
only if the extra specification ``provisioning:type``
appears in the volume type regardless to the default provisioning type.
Maximum oversubscription value supported for ScaleIO is 10.0.

Default provisioning type
-------------------------

If provisioning type settings are not specified in the volume type,
the default value is set according to the ``san_thin_provision``
option in the configuration file. The default provisioning type
will be ``thin`` if the option is not specified in the configuration
file. To set the default provisioning type ``thick``, set
the ``san_thin_provision`` option to ``false``
in the configuration file, as follows:

.. code-block:: ini

   san_thin_provision = false

The configuration file is usually located in
``/etc/cinder/cinder.conf``.
For a configuration example, see:
:ref:`cinder.conf <cg_configuration_example_emc>`.

ScaleIO Block Storage driver configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Edit the ``cinder.conf`` file by adding the configuration below under
a new section (for example, ``[scaleio]``) and change the ``enable_backends``
setting (in the ``[DEFAULT]`` section) to include this new back end.
The configuration file is usually located at
``/etc/cinder/cinder.conf``.

For a configuration example, refer to the example
:ref:`cinder.conf <cg_configuration_example_emc>` .

ScaleIO driver name
-------------------

Configure the driver name by adding the following parameter:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.dell_emc.scaleio.driver.ScaleIODriver

ScaleIO Gateway server IP
-------------------------

The ScaleIO Gateway provides a REST interface to ScaleIO.

Configure the Gateway server IP address by adding the following parameter:

.. code-block:: ini

   san_ip = ScaleIO GATEWAY IP

ScaleIO Storage Pools
---------------------

Multiple Storage Pools and Protection Domains can be listed for use by
the virtual machines. The list should include every Protection Domain and
Storage Pool pair that you would like Cinder to utilize.

To retrieve the available Storage Pools, use the command
:command:`scli --query_all` and search for available Storage Pools.

Configure the available Storage Pools by adding the following parameter:

.. code-block:: ini

   sio_storage_pools = Comma-separated list of protection domain:storage pool name

ScaleIO user credentials
------------------------

Block Storage requires a ScaleIO user with administrative
privileges. ScaleIO recommends creating a dedicated OpenStack user
account that has an administrative user role.

Refer to the ScaleIO User Guide for details on user account management.

Configure the user credentials by adding the following parameters:

.. code-block:: ini

   san_login = ScaleIO username

   san_password = ScaleIO password

Multiple back ends
~~~~~~~~~~~~~~~~~~

Configuring multiple storage back ends allows you to create several back-end
storage solutions that serve the same Compute resources.

When a volume is created, the scheduler selects the appropriate back end
to handle the request, according to the specified volume type.

.. _cg_configuration_example_emc:

Configuration example
~~~~~~~~~~~~~~~~~~~~~

**cinder.conf example file**

You can update the ``cinder.conf`` file by editing the necessary
parameters as follows:

.. code-block:: ini

   [Default]
   enabled_backends = scaleio

   [scaleio]
   volume_driver = cinder.volume.drivers.dell_emc.scaleio.driver.ScaleIODriver
   volume_backend_name = scaleio
   san_ip = GATEWAY_IP
   sio_storage_pools = Domain1:Pool1,Domain2:Pool2
   san_login = SIO_USER
   san_password = SIO_PASSWD
   san_thin_provision = false

Configuration options
~~~~~~~~~~~~~~~~~~~~~

The ScaleIO driver supports these configuration options:

.. include:: ../../tables/cinder-emc_sio.inc
