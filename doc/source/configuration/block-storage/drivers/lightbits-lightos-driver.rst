=======================
Lightbits Cinder Driver
=======================

The Lightbits(TM) OpenStack driver enables OpenStack
clusters to use Lightbits clustered storage servers. This documentation
explains how to configure Cinder for use with the Lightbits storage
backend system.

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create volume
- Delete volume
- Attach volume
- Detach volume
- Create image from volume
- Live migration
- Volume replication
- Thin provisioning
- Multi-attach
- Supported vendor driver
- Extend volume
- Create snapshot
- Delete snapshot
- Create volume from snapshot
- Create volume from volume (clone)
- Active active deployment support
- Volume retype (host assisted)
- Multi Tenancy support

Lightbits OpenStack Driver Components
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Lightbits OpenStack driver has three components:

- Cinder driver
- Nova libvirt volume driver
- os_brick initiator connector

In addition, it requires the Lightbits ``discovery-client``, provided
with product. The os_brick connector uses the Lightbits
``discovery-client`` to communicate with Lightbits NVMe/TCP discovery
services.

The Cinder Driver
~~~~~~~~~~~~~~~~~

The Cinder driver integrates with Cinder and performs REST operations
against the Lightbits storage cluster. To enable the driver, add the following
to Cinder's configuration file

.. code-block:: ini

   enabled_backends = lightos,<any other storage backend you use>

and

.. code-block:: ini

   [lightos]
   volume_driver = cinder.volume.drivers.lightos.LightOSVolumeDriver
   volume_backend_name = lightos
   lightos_api_address = <TARGET_ACCESS_IPS>
   lightos_api_port = 443
   lightos_jwt=<LIGHTOS_JWT>
   lightos_default_num_replicas = 3
   lightos_default_compression_enabled = False
   lightos_api_service_timeout=30

- ``TARGET_ACCESS_IPS`` are the Lightbits cluster nodes access
  IPs. Multiple nodes should be separated by commas. For example:
  ``lightos_api_address =
  192.168.67.78,192.168.34.56,192.168.12.17``. These IPs are where the
  driver looks for the Lightbits clusters REST API servers.
- ``LIGHTOS_JWT`` is the JWT (JSON Web Token) that is located at the
  Lightbits installation controller. You can find the jwt at
  ``~/lightos-default-admin-jwt``.
- The default number of replicas for volumes is 3, and valid values
  for ``lightos_default_num_replicas`` are 1, 2, or 3.
- The default compression setting is False (i.e., data is uncompressed).
  The default compression setting can also be True to indicate that new
  volumes should be created compressed, assuming no other compression
  setting is specified via the volume type.
  To control compression on a per-volume basis, create volume types for
  compressed and uncompressed, and use them as appropriate.
- The default time to wait for API service response is 30 seconds per
  API endpoint.

Creating volumes with non-default compression, number of replica(s) and
multi tenancy can be done through the volume types mechanism. To create a
new volume type with compression or multi tenancy enabled:

.. code-block:: console

  $ openstack volume type create --property compression='<is> True' volume-with-compression

To create a new volume type with one replica:

.. code-block:: console

   $ openstack volume type create --property lightos:num_replicas=1 volume-with-one-replica

To create a new type for a compressed volume with three replicas:

.. code-block:: console

   $ openstack volume type create --property compression='<is> True' --property lightos:num_replicas=3 volume-with-three-replicas-and-compression

Then create a new volume with one of these volume types:

.. code-block:: console

   $ openstack volume create --size <size> --type <type name> <vol name>

Create a volume type for multi tenancy:

.. code-block:: console

   $ openstack volume type create --property lightos:project_name=project-01 type-with-mt

NVNe/TCP and Asymmetric Namespace Access (ANA)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Lightbits clusters expose their volumes using NVMe/TCP Asynchronous
Namespace Access (ANA). ANA is a relatively new feature in the
NVMe/TCP stack in Linux but it is fully supported in Ubuntu
20.04. Each compute host in the OpenStack cluster needs to be
ANA-capable to provide OpenStack VMs with Lightbits volumes over
NVMe/TCP. For more information on how to set up the compute nodes to
use ANA, see the CentOS Linux Cluster Client Software Installation
section of the Lightbits(TM) Cluster Installation and
Initial Configuration Guide.

Note
~~~~

In the current version, if any of the cluster nodes changes its access
IPs, the Cinder driver's configuration file should be updated with the
cluster nodes access IPs and restarted. As long as the Cinder driver
can access at least one cluster access IP it will work, but will be
susceptible to cluster node failures.

Driver options
~~~~~~~~~~~~~~

The following table contains the configuration options supported by the
Lightbits Cinder driver.

.. config-table::
   :config-target: Lightbits cluster

   cinder.volume.drivers.lightos

Active active deployment support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
To enable active-active deployment, follow these steps:

1. Activate the active-active mode by setting the "cluster" option
   in the "DEFAULT" section.
2. Configure the Distributed Lock Manager (DLM) such as Redis or etcd
   in the "coordination" section.

These options should be added to the cinder.conf file:

.. code-block:: ini

   [DEFAULT]
   cluster = <cluster_name>

   [coordination]
   backend_url = <coordination_backend_url>

For more detailed instructions, please refer to the guidelines at::
https://docs.openstack.org/cinder/latest/contributor/high_availability.html
