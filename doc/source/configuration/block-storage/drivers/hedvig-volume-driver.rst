====================
Hedvig Volume Driver
====================

Hedvig provides software-defined storage for enterprises building private,
hybrid, or multi-cloud environments. Hedvig's patented Universal Data Plane
technology forms a distributed, scale-out cluster that transforms commodity
servers or cloud computing into a unified data fabric.

The Hedvig Cinder Driver interacts with a configured backend Hedvig Cluster
using REST APIs.

Using the Hedvig Volume Driver
------------------------------
With the Hedvig Volume Driver for OpenStack, you can :

- Integrate public and private clouds:
    Build a unified hybrid environment to easily migrate to or from your
    data center and public clouds.
- Set granular virtual disk policies:
    Assign enterprise-class features on a per volume basis to best fit your
    application requirements.
- Connect to any compute environment:
    Use with any hypervisor, application, or bare-metal system.
- Grow seamlessly with an elastic cluster:
    Scale storage performance and capacity on-the-fly with off-the-shelf x86
    servers.
- Deliver predictable performance:
    Receive consistent high-IOPS performance for demanding applications
    through massive parallelism, dedicated flash, and edge cache
    configurations.

Requirement
-----------
Hedvig Volume Driver, version 1.0.0 and later, supports Hedvig release 3.0 and
later.

Supported operations
--------------------
Hedvig supports the core features of OpenStack Cinder:

- Create and delete volumes
- Attach and detach volumes
- Create and delete snapshots
- Create volume from snapshot
- Get volume stats
- Copy image to volume
- Copy volume to image
- Clone volume
- Extend volume
- Enable deduplication, encryption, cache, compression, custom replication
  policy on a volume level using volume-type extra-specs


Hedvig Volume Driver configuration
-----------------------------------

The Hedvig Volume Driver can be configured by editing the cinder.conf file
located in the /etc/cinder/ directory.

.. code-block:: ini

    [DEFAULT]
    enabled_backends=hedvig

    [HEDVIG_BACKEND_NAME]
    volume_driver=cinder.volume.drivers.hedvig.hedvig_cinder.HedvigISCSIDriver
    san_ip=<Comma-separated list of HEDVIG_IP/HOSTNAME of the cluster nodes>
    san_login=HEDVIG_USER
    san_password=HEDVIG_PASSWORD
    san_clustername=HEDVIG_CLUSTER

Run the following commands on the OpenStack Cinder Node to create a Volume
Type for Hedvig:

.. code-block:: console

    cinder type-create HEDVIG_VOLUME_TYPE
    cinder type-key HEDVIG_VOLUME_TYPE  set volume_backend_name=HEDVIG_BACKEND_NAME


This section contains definitions of the terms used above.

HEDVIG_IP/HOSTNAME
    The IP address or hostnames of the Hedvig Storage Cluster Nodes

HEDVIG_USER
    Username to login to the Hedvig Cluster with minimum ``super user``
    (admin) privilege

HEDVIG_PASSWORD
    Password to login to the Hedvig Cluster

HEDVIG_CLUSTER
    Name of the Hedvig Cluster

.. note::

     Restart the ``cinder-volume`` service after updating the ``cinder.conf``
     file to apply the changes and to initialize the Hedvig Volume Driver.

Hedvig QoS Spec parameters and values
-------------------------------------

- dedup_enable – true/false
- compressed_enable – true/false
- cache_enable – true/false
- replication_factor – 1-6
- replication_policy – Agnostic/RackAware/DataCenterAware
- replication_policy_info – comma-separated list of data center names
  (applies only to a replication_policy of DataCenterAware)
- disk_residence – Flash/HDD
- encryption – true/false

Creating a Hedvig Cinder Volume with custom attributes (QoS Specs)
------------------------------------------------------------------
1. Create a QoS Spec with the list of attributes that you want to
   associate with a volume. For example, to create a Cinder Volume with
   deduplication enabled, create a QoS Spec called dedup_enable with
   dedup_enable=true
#. Create a new volume type and associate this QoS Spec with it,
   OR associate the QoS Spec with an existing volume type.
#. Every Cinder Volume that you create of the above volume type
   will have deduplication enabled.
#. If you do create a new volume type, make sure to add the key
   volume_backend_name so OpenStack knows that the Hedvig Volume
   Driver handles all requests for this volume.
