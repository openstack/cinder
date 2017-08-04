==============================================
EMC XtremIO Block Storage driver configuration
==============================================

The high performance XtremIO All Flash Array (AFA) offers Block Storage
services to OpenStack. Using the driver, OpenStack Block Storage hosts
can connect to an XtremIO Storage cluster.

This section explains how to configure and connect the block
storage nodes to an XtremIO storage cluster.

Support matrix
~~~~~~~~~~~~~~

XtremIO version 4.x is supported.

Supported operations
~~~~~~~~~~~~~~~~~~~~

-  Create, delete, clone, attach, and detach volumes.

-  Create and delete volume snapshots.

-  Create a volume from a snapshot.

-  Copy an image to a volume.

-  Copy a volume to an image.

-  Extend a volume.

-  Manage and unmanage a volume.

-  Manage and unmanage a snapshot.

-  Get volume statistics.

-  Create, modify, delete, and list consistency groups.

-  Create, modify, delete, and list snapshots of consistency groups.

-  Create consistency group from consistency group or consistency group
   snapshot.

-  Volume Migration (host assisted)

XtremIO Block Storage driver configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Edit the ``cinder.conf`` file by adding the configuration below under
the [DEFAULT] section of the file in case of a single back end or
under a separate section in case of multiple back ends (for example
[XTREMIO]). The configuration file is usually located under the
following path ``/etc/cinder/cinder.conf``.

.. include:: ../../tables/cinder-emc_xtremio.inc

For a configuration example, refer to the configuration
:ref:`emc_extremio_configuration_example`.

XtremIO driver name
-------------------

Configure the driver name by setting the following parameter in the
``cinder.conf`` file:

-  For iSCSI:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.emc.xtremio.XtremIOISCSIDriver

-  For Fibre Channel:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.emc.xtremio.XtremIOFibreChannelDriver

XtremIO management server (XMS) IP
----------------------------------

To retrieve the management IP, use the :command:`show-xms` CLI command.

Configure the management IP by adding the following parameter:

.. code-block:: ini

   san_ip = XMS Management IP

XtremIO cluster name
--------------------

In XtremIO version 4.0, a single XMS can manage multiple cluster back ends. In
such setups, the administrator is required to specify the cluster name (in
addition to the XMS IP). Each cluster must be defined as a separate back end.

To retrieve the cluster name, run the :command:`show-clusters` CLI command.

Configure the cluster name by adding the following parameter:

.. code-block:: ini

   xtremio_cluster_name = Cluster-Name

.. note::

   When a single cluster is managed in XtremIO version 4.0, the cluster name is
   not required.

XtremIO user credentials
------------------------

OpenStack Block Storage requires an XtremIO XMS user with administrative
privileges. XtremIO recommends creating a dedicated OpenStack user account that
holds an administrative user role.

Refer to the XtremIO User Guide for details on user account management.

Create an XMS account using either the XMS GUI or the
:command:`add-user-account` CLI command.

Configure the user credentials by adding the following parameters:

.. code-block:: ini

   san_login = XMS username
   san_password = XMS username password

Multiple back ends
~~~~~~~~~~~~~~~~~~

Configuring multiple storage back ends enables you to create several back-end
storage solutions that serve the same OpenStack Compute resources.

When a volume is created, the scheduler selects the appropriate back end to
handle the request, according to the specified volume type.

Setting thin provisioning and multipathing parameters
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To support thin provisioning and multipathing in the XtremIO Array, the
following parameters from the Nova and Cinder configuration files should be
modified as follows:

-  Thin Provisioning

   All XtremIO volumes are thin provisioned. The default value of 20 should be
   maintained for the ``max_over_subscription_ratio`` parameter.

   The ``use_cow_images`` parameter in the ``nova.conf`` file should be set to
   ``False`` as follows:

   .. code-block:: ini

      use_cow_images = False

-  Multipathing

   The ``use_multipath_for_image_xfer`` parameter in the ``cinder.conf`` file
   should be set to ``True`` as follows:

   .. code-block:: ini

      use_multipath_for_image_xfer = True


Image service optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~

Limit the number of copies (XtremIO snapshots) taken from each image cache.

.. code-block:: ini

    xtremio_volumes_per_glance_cache = 100

The default value is ``100``. A value of ``0`` ignores the limit and defers to
the array maximum as the effective limit.

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

Configuring CHAP
~~~~~~~~~~~~~~~~

The XtremIO Block Storage driver supports CHAP initiator authentication and
discovery.

If CHAP initiator authentication is required, set the CHAP
Authentication mode to initiator.

To set the CHAP initiator mode using CLI, run the following XMCLI command:

.. code-block:: console

   $ modify-chap chap-authentication-mode=initiator

If CHAP initiator discovery is required, set the CHAP discovery mode to
initiator.

To set the CHAP initiator discovery mode using CLI, run the following XMCLI
command:

.. code-block:: console

   $ modify-chap chap-discovery-mode=initiator

The CHAP initiator modes can also be set via the XMS GUI.

Refer to XtremIO User Guide for details on CHAP configuration via GUI and CLI.

The CHAP initiator authentication and discovery credentials (username and
password) are generated automatically by the Block Storage driver. Therefore,
there is no need to configure the initial CHAP credentials manually in XMS.

.. _emc_extremio_configuration_example:

Configuration example
~~~~~~~~~~~~~~~~~~~~~

You can update the ``cinder.conf`` file by editing the necessary parameters as
follows:

.. code-block:: ini

   [Default]
   enabled_backends = XtremIO

   [XtremIO]
   volume_driver = cinder.volume.drivers.emc.xtremio.XtremIOFibreChannelDriver
   san_ip = XMS_IP
   xtremio_cluster_name = Cluster01
   san_login = XMS_USER
   san_password = XMS_PASSWD
   volume_backend_name = XtremIOAFA
