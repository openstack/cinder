=====================================
Dell EMC ScaleIO Block Storage driver
=====================================

Overview
--------

ScaleIO is a software-only solution that uses existing servers' local
disks and LAN to create a virtual SAN that has all of the benefits of
external storage, but at a fraction of the cost and complexity. Using the
driver, Block Storage hosts can connect to a ScaleIO Storage
cluster.

.. _scale_io_docs:

Official ScaleIO documentation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To find the ScaleIO documentation:

#. Go to the `ScaleIO product documentation page <https://support.emc.com/products/33925_ScaleIO/Documentation/?source=promotion>`_.

#. From the left-side panel, select the relevant ScaleIO version.

Supported ScaleIO Versions
~~~~~~~~~~~~~~~~~~~~~~~~~~

The Dell EMC ScaleIO Block Storage driver has been tested against the
following versions of ScaleIO and found to be compatible:

* ScaleIO 2.0.x
* ScaleIO 2.5.x

Please consult the :ref:`scale_io_docs`
to determine supported operating systems for each version of ScaleIO.

Deployment prerequisites
~~~~~~~~~~~~~~~~~~~~~~~~

* ScaleIO Gateway must be installed and accessible in the network.
  For installation steps, refer to the Preparing the installation Manager
  and the Gateway section in ScaleIO Deployment Guide. See
  :ref:`scale_io_docs`.

* ScaleIO Data Client (SDC) must be installed on all OpenStack nodes.

.. note:: Ubuntu users must follow the specific instructions in the ScaleIO
          Deployment Guide for Ubuntu environments. See the ``Deploying on
          Ubuntu Servers`` section in ScaleIO Deployment Guide. See
          :ref:`scale_io_docs`.

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


ScaleIO Block Storage driver configuration
------------------------------------------

This section explains how to configure and connect the block storage
nodes to a ScaleIO storage cluster.

Edit the ``cinder.conf`` file by adding the configuration below under
a new section (for example, ``[scaleio]``) and change the ``enable_backends``
setting (in the ``[DEFAULT]`` section) to include this new back end.
The configuration file is usually located at
``/etc/cinder/cinder.conf``.

For a configuration example, refer to the example
:ref:`cinder.conf <cg_configuration_example_emc>` .

ScaleIO driver name
~~~~~~~~~~~~~~~~~~~

Configure the driver name by adding the following parameter:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.dell_emc.scaleio.driver.ScaleIODriver

ScaleIO Gateway server IP
~~~~~~~~~~~~~~~~~~~~~~~~~

The ScaleIO Gateway provides a REST interface to ScaleIO.

Configure the Gateway server IP address by adding the following parameter:

.. code-block:: ini

   san_ip = <ScaleIO GATEWAY IP>

ScaleIO Storage Pools
~~~~~~~~~~~~~~~~~~~~~

Multiple Storage Pools and Protection Domains can be listed for use by
the virtual machines. The list should include every Protection Domain and
Storage Pool pair that you would like Cinder to utilize.

To retrieve the available Storage Pools, use the command
:command:`scli --query_all` and search for available Storage Pools.

Configure the available Storage Pools by adding the following parameter:

.. code-block:: ini

   sio_storage_pools = <Comma-separated list of protection domain:storage pool name>

ScaleIO user credentials
~~~~~~~~~~~~~~~~~~~~~~~~

Block Storage requires a ScaleIO user with administrative
privileges. ScaleIO recommends creating a dedicated OpenStack user
account that has an administrative user role.

Refer to the ScaleIO User Guide for details on user account management.

Configure the user credentials by adding the following parameters:

.. code-block:: ini

   san_login = <SIO_USER>
   san_password = <SIO_PASSWD>

Oversubscription
~~~~~~~~~~~~~~~~

Configure the oversubscription ratio by adding the following parameter
under the separate section for ScaleIO:

.. code-block:: ini

   sio_max_over_subscription_ratio = <OVER_SUBSCRIPTION_RATIO>

.. note::

   The default value for ``sio_max_over_subscription_ratio``
   is 10.0.

Oversubscription is calculated correctly by the Block Storage service
only if the extra specification ``provisioning:type``
appears in the volume type regardless of the default provisioning type.
Maximum oversubscription value supported for ScaleIO is 10.0.

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

Volume Types
------------

Volume types can be used to specify characteristics of volumes allocated via the
ScaleIO Driver. These characteristics are defined as ``Extra Specs`` within
``Volume Types``.

ScaleIO Protection Domain and Storage Pool
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When multiple storage pools are specified in the Cinder configuration,
users can specify which pool should be utilized by adding the ``pool``
Extra Spec to the volume type extra-specs and setting the value to the
requested protection_domain:storage_pool.

.. code-block:: console

   $ openstack volume type create sio_type_1
   $ openstack volume type set --property volume_backend_name=scaleio sio_type_1
   $ openstack volume type set --property pool=Domain2:Pool2 sio_type_1

ScaleIO thin provisioning support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Block Storage driver supports creation of thin-provisioned and
thick-provisioned volumes.
The provisioning type settings can be added as an extra specification
of the volume type, as follows:

.. code-block:: console

   $ openstack volume type create sio_type_thick
   $ openstack volume type set --property provisioning:type=thick sio_type_thick

ScaleIO QoS support
~~~~~~~~~~~~~~~~~~~

QoS support for the ScaleIO driver includes the ability to set the
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
   $ openstack volume type create sio_limit_iops
   $ openstack volume qos associate qos-limit-iops sio_limit_iops

The driver always chooses the minimum between the QoS keys value
and the relevant calculated value of ``maxIOPSperGB`` or ``maxBWSperGB``.

Since the limits are per SDC, they will be applied after the volume
is attached to an instance, and thus to a compute node/SDC.

Using ScaleIO Storage with a containerized overcloud
----------------------------------------------------

When using a containerized overcloud, such as one deployed via TripleO or RedHat
Openstack version 12 and above, there is an additional step that must be
performed.

Before deploying the overcloud
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

After ensuring that the ScaleIO Data Client (SDC) is installed on all nodes and
before deploying the overcloud,
modify the TripleO Heat Template for the nova-compute and cinder-volume
containers to add volume mappings for directories containing the SDC
components. These files can normally
be found at
``/usr/share/openstack-tripleo-heat-templates/docker/services/nova-compute.yaml``
and
``/usr/share/openstack-tripleo-heat-templates/docker/services/cinder-volume.yaml``

Two lines need to be inserted into the list of mapped volumes in each container.

.. code-block:: yaml

  /opt/emc/scaleio:/opt/emc/scaleio
  /bin/emc/scaleio:/bin/emc/scaleio

.. end

The changes to the two heat templates are identical, as an example
the original nova-compute file should have section that resembles the following:

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
