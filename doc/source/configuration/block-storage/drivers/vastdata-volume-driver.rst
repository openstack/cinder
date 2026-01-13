==========================
VAST Data Volume Driver
==========================

The VAST Data Volume driver integrates OpenStack
with VAST Data's Storage System.
Volumes in the Block Storage service are backed
by VAST's NVMe storage and are accessed using VAST's API.

This documentation explains how to configure and connect
the Block Storage nodes to the VAST Data storage system.

Prerequisites
~~~~~~~~~~~~~

Before configuring the VAST Data volume driver, ensure the following
prerequisites are met:

**Network Configuration**

Ensure your OpenStack environment has network connectivity to:

- **Management Network**: Access to VAST VMS/Web UI (typically port 443)
- **Data Network**: Access to VAST VIP pool for NVMe connections (port 4420)

**NVMe Tools Installation**

The NVMe CLI tools must be installed on all compute nodes that will
attach VAST volumes:

.. code-block:: console

   # On RHEL/CentOS/Fedora
   $ sudo yum install nvme-cli

   # On Ubuntu/Debian
   $ sudo apt-get install nvme-cli

**Kernel Modules**

Load the necessary kernel modules for NVMe over Fabrics on all compute nodes:

.. code-block:: console

   $ sudo modprobe nvme
   $ sudo modprobe nvme-fabrics

To ensure these modules load automatically on boot, add them to
``/etc/modules-load.d/nvme.conf``:

.. code-block:: console

   $ echo "nvme" | sudo tee -a /etc/modules-load.d/nvme.conf
   $ echo "nvme-fabrics" | sudo tee -a /etc/modules-load.d/nvme.conf

**VAST Cluster Configuration**

On your VAST cluster, ensure the following resources are configured:

- A VIP pool for NVMe/TCP connections
- A subsystem for block storage operations
- Admin credentials or API token for management access

Driver options
~~~~~~~~~~~~~~

.. include:: ../../tables/cinder-vastdata.inc

Supported operations
~~~~~~~~~~~~~~~~~~~~

The VAST Data volume driver supports the following operations:

- Create, list, delete, attach (map), and detach (unmap) volumes
- Create, list and delete volume snapshots
- Create a volume from a snapshot
- Clone a volume
- Extend a volume
- Multi-attach volumes (attach same volume to multiple instances)

Configuring the VAST Data Backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section details the steps required
to configure the VAST Data storage driver for Cinder.

Configuration Steps
-------------------

#. Edit the ``/etc/cinder/cinder.conf`` configuration file.

#. In the ``[DEFAULT]`` section, add ``vast`` to the
   ``enabled_backends`` parameter:

   .. code-block:: ini

      [DEFAULT]
      enabled_backends = vast

#. Add a new ``[vast]`` backend group section with the following
   required options:

   .. code-block:: ini

      [vast]
      # The driver path (required)
      volume_driver = cinder.volume.drivers.vastdata.driver.VASTVolumeDriver

      # Backend name (required)
      volume_backend_name = vast

      # Management IP of the VAST storage system (required)
      san_ip = 10.0.0.100

      # Management API port (optional, default: 443)
      san_api_port = 443

      # Management username (required if not using API token)
      san_login = admin

      # Management password (required if not using API token)
      san_password = password123

      # API token (optional, replaces san_login/san_password)
      # vast_api_token = your-api-token-here

      # Virtual IP Pool for NVMe connections (required)
      vast_vippool_name = vip-pool1

      # Subsystem for NVMe (required)
      vast_subsystem = cinder-subsystem

      # Tenant name (optional, for multi-tenant environments)
      # vast_tenant_name = tenant1

      # Volume name prefix (optional, default: openstack-vol-)
      # vast_volume_prefix = openstack-vol-

      # Snapshot name prefix (optional, default: openstack-snap-)
      # vast_snapshot_prefix = openstack-snap-

      # SSL certificate verification (optional, default: False)
      # driver_ssl_cert_verify = True

      # Path to CA certificate file or directory (optional)
      # driver_ssl_cert_path = /etc/cinder/vast_ca.pem


#. Restart the cinder-volume service to apply the configuration:

   .. code-block:: console

      # On systemd-based systems
      $ sudo systemctl restart openstack-cinder-volume.service

      # Or if using devstack
      $ sudo systemctl restart devstack@c-vol.service

#. Verify the service started successfully:

   .. code-block:: console

      $ sudo systemctl status openstack-cinder-volume.service
      $ openstack volume service list

Example Configuration
---------------------

Here is a complete working example of a VAST backend configuration:

.. code-block:: ini

   [DEFAULT]
   enabled_backends = vast
   debug = False

   [vast]
   volume_driver = cinder.volume.drivers.vastdata.driver.VASTVolumeDriver
   volume_backend_name = vast
   san_ip = 10.27.200.100
   san_api_port = 443
   san_login = admin
   san_password = VastAdmin123!
   vast_vippool_name = vip-pool-nvme
   vast_subsystem = openstack-cinder

SSL Certificate Verification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default, SSL certificate verification is disabled. To enable secure
HTTPS communication with the VAST storage system, you can configure
SSL certificate verification.

**Option 1: Enable SSL verification with system CA bundle**

.. code-block:: ini

   [vast]
   ...
   driver_ssl_cert_verify = True
   ...

**Option 2: Enable SSL verification with custom CA certificate**

#. Obtain the SSL certificate from your VAST storage.

#. Copy the certificate to a location accessible by the cinder-volume service,
   for example: ``/etc/cinder/vast_ca.pem``

#. Configure the driver to use the custom certificate:

   .. code-block:: ini

      [vast]
      ...
      driver_ssl_cert_verify = True
      driver_ssl_cert_path = /etc/cinder/vast_ca.pem
      ...

#. Restart the cinder-volume service for the changes to take effect.

.. note::

   If ``driver_ssl_cert_path`` is omitted when ``driver_ssl_cert_verify = True``,
   the system's default CA bundle will be used. The ``driver_ssl_cert_path`` can point
   to either a CA_BUNDLE file (e.g., ``/path/to/ca-bundle.crt``) or a directory
   containing CA certificates (e.g., ``/etc/ssl/certs/``).

Usage Examples
~~~~~~~~~~~~~~

This section provides practical examples of common operations using
the VAST Data volume driver with OpenStack CLI commands.

Create a Volume Type
--------------------

First, create a volume type for VAST storage:

.. code-block:: console

   $ openstack volume type create vast \
        --property volume_backend_name=vast

Create a Volume
---------------

Create a new volume with the VAST volume type:

.. code-block:: console

   $ openstack volume create --size 100 --type vast my-vast-volume

This creates a 100 GiB volume named ``my-vast-volume`` on VAST storage.

List Volumes
------------

View all volumes:

.. code-block:: console

   $ openstack volume list

View details of a specific volume:

.. code-block:: console

   $ openstack volume show my-vast-volume

Attach Volume to Instance
--------------------------

Attach a volume to a running instance:

.. code-block:: console

   $ openstack server add volume <instance-name-or-id> <volume-name-or-id>

Verify the attachment:

.. code-block:: console

   $ openstack server volume list my-instance

Detach Volume from Instance
----------------------------

Detach a volume from an instance:

.. code-block:: console

   $ openstack server remove volume <instance-name-or-id> <volume-name-or-id>

Extend a Volume
---------------

Increase the size of an existing volume:

.. code-block:: console

   $ openstack volume set --size <new-size> <volume-name-or-id>

Create a Volume Snapshot
-------------------------

Create a snapshot of an existing volume:

.. code-block:: console

   $ openstack volume snapshot create \
       --volume <volume-name-or-id> \
       --description "My snapshot description" \
       my-snapshot

List snapshots:

.. code-block:: console

   $ openstack volume snapshot list

View snapshot details:

.. code-block:: console

   $ openstack volume snapshot show my-snapshot

Create Volume from Snapshot
----------------------------

Create a new volume from an existing snapshot:

.. code-block:: console

   $ openstack volume create \
       --snapshot <snapshot-name-or-id> \
       --size 100 \
       --type vast \
       restored-volume

.. note::

   The new volume size must be equal to or larger than the original snapshot size.

Delete a Snapshot
-----------------

Delete a volume snapshot:

.. code-block:: console

   $ openstack volume snapshot delete <snapshot-name-or-id>

Clone a Volume
--------------

Create a new volume by cloning an existing volume:

.. code-block:: console

   $ openstack volume create \
       --source <source-volume-name-or-id> \
       --size 100 \
       --type vast \
       cloned-volume

Delete a Volume
---------------

Delete a volume (must be detached first):

.. code-block:: console

   $ openstack volume delete <volume-name-or-id>

Multi-attach Volumes
--------------------

The VAST driver supports multi-attach, allowing a single volume to be
attached to multiple instances simultaneously.

Create a multi-attach enabled volume type:

.. code-block:: console

   $ openstack volume type create vast-multiattach \
       --property multiattach="<is> True" \
       --property volume_backend_name=vast

Create a multi-attach volume:

.. code-block:: console

   $ openstack volume create \
       --size 100 \
       --type vast-multiattach \
       shared-volume

Attach to multiple instances:

.. code-block:: console

   $ openstack server add volume instance1 shared-volume
   $ openstack server add volume instance2 shared-volume

Troubleshooting
~~~~~~~~~~~~~~~

Common Issues
-------------

**Volume attachment fails**

- Verify NVMe CLI tools are installed on compute nodes
- Check that nvme and nvme-fabrics kernel modules are loaded
- Ensure network connectivity between compute nodes and VAST VIP pool
- Verify the VIP pool name and subsystem are configured correctly

**Cannot create volumes**

- Verify management credentials (san_ip, san_login, san_password or
  vast_api_token)
- Check network connectivity to VAST VMS
- Ensure the subsystem exists on the VAST cluster
- Verify sufficient capacity is available on the VAST cluster
