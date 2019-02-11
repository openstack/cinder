===========================================
Dell EMC VxFlex OS (ScaleIO) Storage driver
===========================================

Overview
--------

Dell EMC VxFlex OS (formerly named Dell EMC ScaleIO) is a software-only
solution that uses existing servers local
disks and LAN to create a virtual SAN that has all of the benefits of
external storage, but at a fraction of the cost and complexity. Using the
driver, Block Storage hosts can connect to a VxFlex OS Storage
cluster.

The Dell EMC VxFlex OS Cinder driver is designed and tested to work with
both VxFlex OS and with ScaleIO. The
:ref:`configuration options <cg_configuration_options_emc>`
are identical for both VxFlex OS and ScaleIO.

.. _scaleio_docs:

Official VxFlex OS documentation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To find the VxFlex OS documentation:

#. Go to the `VxFlex OS product documentation page <https://support.emc.com/products/33925_ScaleIO/Documentation/?source=promotion>`_.

#. From the left-side panel, select the relevant VxFlex OS version.

Supported VxFlex OS and ScaleIO Versions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Dell EMC VxFlex OS Block Storage driver has been tested against the
following versions of ScaleIO and VxFlex OS and found to be compatible:

* ScaleIO 2.0.x
* ScaleIO 2.5.x
* VxFlex OS 2.6.x
* VxFlex OS 3.0.x

Please consult the :ref:`scaleio_docs`
to determine supported operating systems for each version
of VxFlex OS or ScaleIO.

Deployment prerequisites
~~~~~~~~~~~~~~~~~~~~~~~~

* The VxFlex OS Gateway must be installed and accessible in the network.
  For installation steps, refer to the Preparing the installation Manager
  and the Gateway section in VxFlex OS Deployment Guide. See
  :ref:`scaleio_docs`.

* VxFlex OS Storage Data Client (SDC) must be installed
  on all OpenStack nodes.

.. note:: Ubuntu users must follow the specific instructions in the VxFlex
          OS Deployment Guide for Ubuntu environments. See the ``Deploying
          on Ubuntu Servers`` section in VxFlex OS Deployment Guide. See
          :ref:`scaleio_docs`.

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


VxFlex OS Block Storage driver configuration
--------------------------------------------

This section explains how to configure and connect the block storage
nodes to a VxFlex OS storage cluster.

Edit the ``cinder.conf`` file by adding the configuration below under
a new section (for example, ``[vxflexos]``) and change the ``enable_backends``
setting (in the ``[DEFAULT]`` section) to include this new back end.
The configuration file is usually located at
``/etc/cinder/cinder.conf``.

For a configuration example, refer to the example
:ref:`cinder.conf <cg_configuration_example_emc>` .

VxFlex OS driver name
~~~~~~~~~~~~~~~~~~~~~

Configure the driver name by adding the following parameter:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.dell_emc.vxflexos.driver.VxFlexOSDriver

VxFlex OS Gateway server IP
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The VxFlex OS Gateway provides a REST interface to VxFlex OS.

Configure the Gateway server IP address by adding the following parameter:

.. code-block:: ini

   san_ip = <VxFlex OS GATEWAY IP>

VxFlex OS Storage Pools
~~~~~~~~~~~~~~~~~~~~~~~

Multiple Storage Pools and Protection Domains can be listed for use by
the virtual machines. The list should include every Protection Domain and
Storage Pool pair that you would like Cinder to utilize.

To retrieve the available Storage Pools, use the command
:command:`scli --query_all` and search for available Storage Pools.

Configure the available Storage Pools by adding the following parameter:

.. code-block:: ini

   vxflexos_storage_pools = <Comma-separated list of protection domain:storage pool name>

VxFlex OS user credentials
~~~~~~~~~~~~~~~~~~~~~~~~~~

Block Storage requires a VxFlex OS user with administrative
privileges. Dell EMC recommends creating a dedicated OpenStack user
account that has an administrative user role.

Refer to the VxFlex OS User Guide for details on user account management.

Configure the user credentials by adding the following parameters:

.. code-block:: ini

   san_login = <SIO_USER>
   san_password = <SIO_PASSWD>

Oversubscription
~~~~~~~~~~~~~~~~

Configure the oversubscription ratio by adding the following parameter
under the separate section for VxFlex OS:

.. code-block:: ini

   vxflexos_max_over_subscription_ratio = <OVER_SUBSCRIPTION_RATIO>

.. note::

   The default value for ``vxflexos_max_over_subscription_ratio``
   is 10.0.

Oversubscription is calculated correctly by the Block Storage service
only if the extra specification ``provisioning:type``
appears in the volume type regardless of the default provisioning type.
Maximum oversubscription value supported for VxFlex OS is 10.0.

Default provisioning type
~~~~~~~~~~~~~~~~~~~~~~~~~

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

.. _cg_configuration_example_emc:

Configuration example
~~~~~~~~~~~~~~~~~~~~~

**cinder.conf example file**

You can update the ``cinder.conf`` file by editing the necessary
parameters as follows:

.. code-block:: ini

   [DEFAULT]
   enabled_backends = vxflexos

   [vxflexos]
   volume_driver = cinder.volume.drivers.dell_emc.vxflexos.driver.VxFlexOSDriver
   volume_backend_name = vxflexos
   san_ip = GATEWAY_IP
   vxflexos_storage_pools = Domain1:Pool1,Domain2:Pool2
   san_login = SIO_USER
   san_password = SIO_PASSWD
   san_thin_provision = false

.. _cg_configuration_options_emc:

Configuration options
~~~~~~~~~~~~~~~~~~~~~

The VxFlex OS driver supports these configuration options:

.. config-table::
   :config-target: VxFlex OS

   cinder.volume.drivers.dell_emc.vxflexos.driver

Volume Types
------------

Volume types can be used to specify characteristics of volumes allocated via
the VxFlex OS Driver. These characteristics are defined as ``Extra Specs``
within ``Volume Types``.

VxFlex OS Protection Domain and Storage Pool
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When multiple storage pools are specified in the Cinder configuration,
users can specify which pool should be utilized by adding the ``pool_name``
Extra Spec to the volume type extra-specs and setting the value to the
requested protection_domain:storage_pool.

.. code-block:: console

   $ openstack volume type create vxflexos_type_1
   $ openstack volume type set --property volume_backend_name=vxflexos vxflexos_type_1
   $ openstack volume type set --property pool_name=Domain2:Pool2 vxflexos_type_1

VxFlex OS thin provisioning support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Block Storage driver supports creation of thin-provisioned and
thick-provisioned volumes.
The provisioning type settings can be added as an extra specification
of the volume type, as follows:

.. code-block:: console

   $ openstack volume type create vxflexos_type_thick
   $ openstack volume type set --property provisioning:type=thick vxflexos_type_thick

VxFlex OS QoS support
~~~~~~~~~~~~~~~~~~~~~

QoS support for the VxFlex OS driver includes the ability to set the
following capabilities:

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

The QoS keys above must be created and associated with a volume type.
For example:

.. code-block:: console

   $ openstack volume qos create qos-limit-iops --consumer back-end --property maxIOPS=5000
   $ openstack volume type create vxflexos_limit_iops
   $ openstack volume qos associate qos-limit-iops vxflexos_limit_iops

The driver always chooses the minimum between the QoS keys value
and the relevant calculated value of ``maxIOPSperGB`` or ``maxBWSperGB``.

Since the limits are per SDC, they will be applied after the volume
is attached to an instance, and thus to a compute node/SDC.

VxFlex OS compression support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Starting from version 3.0, VxFlex OS supports volume compression.
By default driver will create volumes without compression.
In order to create a compressed volume, a volume type which enables
compression support needs to be created first:

.. code-block:: console

   $ openstack volume type create vxflexos_compressed
   $ openstack volume type set --property provisioning:type=compressed vxflexos_compressed

If a volume with this type is scheduled to a storage pool which doesn't
support compression, then ``thin`` provisioning will be used.
See table below for details.

+-------------------+---------------------------+--------------------+
| provisioning:type |  storage pool supports compression             |
|                   +---------------------------+--------------------+
|                   | yes (VxFlex 3.0 FG pool)  |  no (other pools)  |
+===================+===========================+====================+
|   compressed      |     thin with compression |     thin           |
+-------------------+---------------------------+--------------------+
|   thin            |        thin               |     thin           |
+-------------------+---------------------------+--------------------+
|   thick           |        thin               |     thick          |
+-------------------+---------------------------+--------------------+
|   not set         |        thin               |     thin           |
+-------------------+---------------------------+--------------------+

.. note::
    VxFlex 3.0 Fine Granularity storage pools don't support thick provisioned volumes.

You can add property ``compression_support='<is> True'`` to volume type to
limit volumes allocation only to data pools which supports compression.

.. code-block:: console

   $ openstack volume type set  --property compression_support='<is> True'  vxflexos_compressed


Using VxFlex OS Storage with a containerized overcloud
------------------------------------------------------

When using a containerized overcloud, such as one deployed via TripleO or
Red Hat OpenStack version 12 and above, there is an additional step that must
be performed.

Before deploying the overcloud
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

After ensuring that the Storage Data Client (SDC) is installed on all nodes and
before deploying the overcloud,
modify the TripleO Heat Template for the nova-compute and cinder-volume
containers to add volume mappings for directories containing the SDC
components. These files can normally
be found at
``/usr/share/openstack-tripleo-heat-templates/docker/services/nova-compute.yaml``
and
``/usr/share/openstack-tripleo-heat-templates/docker/services/cinder-volume.yaml``

Two lines need to be inserted into the list of mapped volumes in each
container.

.. code-block:: yaml

  /opt/emc/scaleio:/opt/emc/scaleio
  /bin/emc/scaleio:/bin/emc/scaleio

.. end

The changes to the two heat templates are identical, as an example
the original nova-compute file should have section that resembles the
following:

.. code-block:: yaml

  ...
  docker_config:
    step_4:
      nova_compute:
        image: &nova_compute_image {get_param: DockerNovaComputeImage}
        ipc: host
        net: host
        privileged: true
        user: nova
        restart: always
        volumes:
          list_concat:
            - {get_attr: [ContainersCommon, volumes]}
            -
              - /var/lib/kolla/config_files/nova_compute.json:/var/lib/kolla/config_files/config.json:ro
              - /var/lib/config-data/puppet-generated/nova_libvirt/:/var/lib/kolla/config_files/src:ro
              - /etc/ceph:/var/lib/kolla/config_files/src-ceph:ro
              - /dev:/dev
              - /lib/modules:/lib/modules:ro
              - /etc/iscsi:/etc/iscsi
              - /run:/run
              - /var/lib/nova:/var/lib/nova:shared
              - /var/lib/libvirt:/var/lib/libvirt
              - /var/log/containers/nova:/var/log/nova
              - /sys/class/net:/sys/class/net
              - /sys/bus/pci:/sys/bus/pci
        environment:
         - KOLLA_CONFIG_STRATEGY=COPY_ALWAYS
  ...

.. end

After modifying the nova-compute file, the section should resemble:

.. code-block:: yaml

  ...
  docker_config:
    step_4:
      nova_compute:
        image: &nova_compute_image {get_param: DockerNovaComputeImage}
        ipc: host
        net: host
        privileged: true
        user: nova
        restart: always
        volumes:
          list_concat:
            - {get_attr: [ContainersCommon, volumes]}
            -
              - /var/lib/kolla/config_files/nova_compute.json:/var/lib/kolla/config_files/config.json:ro
              - /var/lib/config-data/puppet-generated/nova_libvirt/:/var/lib/kolla/config_files/src:ro
              - /etc/ceph:/var/lib/kolla/config_files/src-ceph:ro
              - /dev:/dev
              - /lib/modules:/lib/modules:ro
              - /etc/iscsi:/etc/iscsi
              - /run:/run
              - /var/lib/nova:/var/lib/nova:shared
              - /var/lib/libvirt:/var/lib/libvirt
              - /var/log/containers/nova:/var/log/nova
              - /sys/class/net:/sys/class/net
              - /sys/bus/pci:/sys/bus/pci
              - /opt/emc/scaleio:/opt/emc/scaleio
              - /bin/emc/scaleio:/bin/emc/scaleio
        environment:
         - KOLLA_CONFIG_STRATEGY=COPY_ALWAYS
  ...

.. end

Once the nova-compute file is modified, make an identical change to the
cinder-volume file.


Deploy the overcloud
~~~~~~~~~~~~~~~~~~~~

Once the above changes have been made, deploy the overcloud as usual.
