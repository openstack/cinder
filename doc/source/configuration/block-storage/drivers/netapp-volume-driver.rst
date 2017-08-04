=====================
NetApp unified driver
=====================

The NetApp unified driver is a Block Storage driver that supports
multiple storage families and protocols. A storage family corresponds to
storage systems built on different NetApp technologies such as clustered
Data ONTAP, Data ONTAP operating in 7-Mode, and E-Series. The storage
protocol refers to the protocol used to initiate data storage and access
operations on those storage systems like iSCSI and NFS. The NetApp
unified driver can be configured to provision and manage OpenStack
volumes on a given storage family using a specified storage protocol.
Also, the NetApp unified driver supports over subscription or over
provisioning when thin provisioned Block Storage volumes are in use
on an E-Series backend. The OpenStack volumes can then be used for
accessing and storing data using the storage protocol on the storage
family system. The NetApp unified driver is an extensible interface
that can support new storage families and protocols.

.. important::

   The NetApp unified driver in cinder currently provides integration for
   two major generations of the ONTAP operating system: the current
   clustered ONTAP and the legacy 7-mode. NetApp’s full support for
   7-mode ended in August of 2015 and the current limited support period
   will end in February of 2017.

   The 7-mode components of the cinder NetApp unified driver have now been
   marked deprecated and will be removed in the Queens release. This will
   apply to all three protocols currently supported in this driver: iSCSI,
   FC and NFS.

.. note::

   With the Juno release of OpenStack, Block Storage has
   introduced the concept of storage pools, in which a single
   Block Storage back end may present one or more logical
   storage resource pools from which Block Storage will
   select a storage location when provisioning volumes.

   In releases prior to Juno, the NetApp unified driver contained some
   scheduling logic that determined which NetApp storage container
   (namely, a FlexVol volume for Data ONTAP, or a dynamic disk pool for
   E-Series) that a new Block Storage volume would be placed into.

   With the introduction of pools, all scheduling logic is performed
   completely within the Block Storage scheduler, as each
   NetApp storage container is directly exposed to the Block
   Storage scheduler as a storage pool. Previously, the NetApp
   unified driver presented an aggregated view to the scheduler and
   made a final placement decision as to which NetApp storage container
   the Block Storage volume would be provisioned into.

NetApp clustered Data ONTAP storage family
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The NetApp clustered Data ONTAP storage family represents a
configuration group which provides Compute instances access to
clustered Data ONTAP storage systems. At present it can be configured in
Block Storage to work with iSCSI and NFS storage protocols.

NetApp iSCSI configuration for clustered Data ONTAP
---------------------------------------------------

The NetApp iSCSI configuration for clustered Data ONTAP is an interface
from OpenStack to clustered Data ONTAP storage systems. It provisions
and manages the SAN block storage entity, which is a NetApp LUN that
can be accessed using the iSCSI protocol.

The iSCSI configuration for clustered Data ONTAP is a direct interface
from Block Storage to the clustered Data ONTAP instance and as
such does not require additional management software to achieve the
desired functionality. It uses NetApp APIs to interact with the
clustered Data ONTAP instance.

**Configuration options**

Configure the volume driver, storage family, and storage protocol to the
NetApp unified driver, clustered Data ONTAP, and iSCSI respectively by
setting the ``volume_driver``, ``netapp_storage_family`` and
``netapp_storage_protocol`` options in the ``cinder.conf`` file as follows:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.netapp.common.NetAppDriver
   netapp_storage_family = ontap_cluster
   netapp_storage_protocol = iscsi
   netapp_vserver = openstack-vserver
   netapp_server_hostname = myhostname
   netapp_server_port = port
   netapp_login = username
   netapp_password = password

.. note::

   To use the iSCSI protocol, you must override the default value of
   ``netapp_storage_protocol`` with ``iscsi``.

.. include:: ../../tables/cinder-netapp_cdot_iscsi.inc

.. note::

   If you specify an account in the ``netapp_login`` that only has
   virtual storage server (Vserver) administration privileges (rather
   than cluster-wide administration privileges), some advanced features
   of the NetApp unified driver will not work and you may see warnings
   in the Block Storage logs.

.. note::

   The driver supports iSCSI CHAP uni-directional authentication.
   To enable it, set the ``use_chap_auth`` option to ``True``.

.. tip::

   For more information on these options and other deployment and
   operational scenarios, visit the `NetApp OpenStack Deployment and
   Operations
   Guide <http://netapp.github.io/openstack-deploy-ops-guide/>`__.

NetApp NFS configuration for clustered Data ONTAP
-------------------------------------------------

The NetApp NFS configuration for clustered Data ONTAP is an interface from
OpenStack to a clustered Data ONTAP system for provisioning and managing
OpenStack volumes on NFS exports provided by the clustered Data ONTAP system
that are accessed using the NFS protocol.

The NFS configuration for clustered Data ONTAP is a direct interface from
Block Storage to the clustered Data ONTAP instance and as such does
not require any additional management software to achieve the desired
functionality. It uses NetApp APIs to interact with the clustered Data ONTAP
instance.

**Configuration options**

Configure the volume driver, storage family, and storage protocol to NetApp
unified driver, clustered Data ONTAP, and NFS respectively by setting the
``volume_driver``, ``netapp_storage_family``, and ``netapp_storage_protocol``
options in the ``cinder.conf`` file as follows:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.netapp.common.NetAppDriver
   netapp_storage_family = ontap_cluster
   netapp_storage_protocol = nfs
   netapp_vserver = openstack-vserver
   netapp_server_hostname = myhostname
   netapp_server_port = port
   netapp_login = username
   netapp_password = password
   nfs_shares_config = /etc/cinder/nfs_shares

.. include:: ../../tables/cinder-netapp_cdot_nfs.inc

.. note::

   Additional NetApp NFS configuration options are shared with the
   generic NFS driver. These options can be found here:
   :ref:`cinder-storage_nfs`.

.. note::

   If you specify an account in the ``netapp_login`` that only has
   virtual storage server (Vserver) administration privileges (rather
   than cluster-wide administration privileges), some advanced features
   of the NetApp unified driver will not work and you may see warnings
   in the Block Storage logs.

NetApp NFS Copy Offload client
------------------------------

A feature was added in the Icehouse release of the NetApp unified driver that
enables Image service images to be efficiently copied to a destination Block
Storage volume. When the Block Storage and Image service are configured to use
the NetApp NFS Copy Offload client, a controller-side copy will be attempted
before reverting to downloading the image from the Image service. This improves
image provisioning times while reducing the consumption of bandwidth and CPU
cycles on the host(s) running the Image and Block Storage services. This is due
to the copy operation being performed completely within the storage cluster.

The NetApp NFS Copy Offload client can be used in either of the following
scenarios:

- The Image service is configured to store images in an NFS share that is
  exported from a NetApp FlexVol volume *and* the destination for the new Block
  Storage volume will be on an NFS share exported from a different FlexVol
  volume than the one used by the Image service. Both FlexVols must be located
  within the same cluster.

- The source image from the Image service has already been cached in an NFS
  image cache within a Block Storage back end. The cached image resides on a
  different FlexVol volume than the destination for the new Block Storage
  volume. Both FlexVols must be located within the same cluster.

To use this feature, you must configure the Image service, as follows:

- Set the ``default_store`` configuration option to ``file``.

- Set the ``filesystem_store_datadir`` configuration option to the path
  to the Image service NFS export.

- Set the ``show_image_direct_url`` configuration option to ``True``.

- Set the ``show_multiple_locations`` configuration option to ``True``.

- Set the ``filesystem_store_metadata_file`` configuration option to a metadata
  file. The metadata file should contain a JSON object that contains the
  correct information about the NFS export used by the Image service.

To use this feature, you must configure the Block Storage service, as follows:

- Set the ``netapp_copyoffload_tool_path`` configuration option to the path to
  the NetApp Copy Offload binary.

- Set the ``glance_api_version`` configuration option to ``2``.

  .. important::

     This feature requires that:

     - The storage system must have Data ONTAP v8.2 or greater installed.

     - The vStorage feature must be enabled on each storage virtual machine
       (SVM, also known as a Vserver) that is permitted to interact with the
       copy offload client.

     - To configure the copy offload workflow, enable NFS v4.0 or greater and
       export it from the SVM.

.. tip::

   To download the NetApp copy offload binary to be utilized in conjunction
   with the ``netapp_copyoffload_tool_path`` configuration option, please visit
   the Utility Toolchest page at the `NetApp Support portal
   <http://mysupport.netapp.com/NOW/download/tools/ntap_openstack_nfs/>`__
   (login is required).

.. tip::

   For more information on these options and other deployment and operational
   scenarios, visit the `NetApp OpenStack Deployment and Operations Guide
   <http://netapp.github.io/openstack-deploy-ops-guide/>`__.

NetApp-supported extra specs for clustered Data ONTAP
-----------------------------------------------------

Extra specs enable vendors to specify extra filter criteria.
The Block Storage scheduler uses the specs when the scheduler determines
which volume node should fulfill a volume provisioning request.
When you use the NetApp unified driver with a clustered Data ONTAP
storage system, you can leverage extra specs with Block Storage
volume types to ensure that Block Storage volumes are created
on storage back ends that have certain properties.
An example of this is when you configure QoS, mirroring,
or compression for a storage back end.

Extra specs are associated with Block Storage volume types.
When users request volumes of a particular volume type, the volumes
are created on storage back ends that meet the list of requirements.
An example of this is the back ends that have the available space or
extra specs. Use the specs in the following table to configure volumes.
Define Block Storage volume types by using the :command:`openstack volume
type set` command.

.. include:: ../../tables/manual/cinder-netapp_cdot_extraspecs.inc


NetApp Data ONTAP operating in 7-Mode storage family
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The NetApp Data ONTAP operating in 7-Mode storage family represents a
configuration group which provides Compute instances access to 7-Mode
storage systems. At present it can be configured in Block Storage to
work with iSCSI and NFS storage protocols.

NetApp iSCSI configuration for Data ONTAP operating in 7-Mode
-------------------------------------------------------------

The NetApp iSCSI configuration for Data ONTAP operating in 7-Mode is an
interface from OpenStack to Data ONTAP operating in 7-Mode storage systems for
provisioning and managing the SAN block storage entity, that is, a LUN which
can be accessed using iSCSI protocol.

The iSCSI configuration for Data ONTAP operating in 7-Mode is a direct
interface from OpenStack to Data ONTAP operating in 7-Mode storage system and
it does not require additional management software to achieve the desired
functionality. It uses NetApp ONTAPI to interact with the Data ONTAP operating
in 7-Mode storage system.

**Configuration options**

Configure the volume driver, storage family and storage protocol to the NetApp
unified driver, Data ONTAP operating in 7-Mode, and iSCSI respectively by
setting the ``volume_driver``, ``netapp_storage_family`` and
``netapp_storage_protocol`` options in the ``cinder.conf`` file as follows:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.netapp.common.NetAppDriver
   netapp_storage_family = ontap_7mode
   netapp_storage_protocol = iscsi
   netapp_server_hostname = myhostname
   netapp_server_port = 80
   netapp_login = username
   netapp_password = password

.. note::

   To use the iSCSI protocol, you must override the default value of
   ``netapp_storage_protocol`` with ``iscsi``.

.. include:: ../../tables/cinder-netapp_7mode_iscsi.inc

.. note::

   The driver supports iSCSI CHAP uni-directional authentication.
   To enable it, set the ``use_chap_auth`` option to ``True``.

.. tip::

   For more information on these options and other deployment and
   operational scenarios, visit the `NetApp OpenStack Deployment and
   Operations
   Guide <http://netapp.github.io/openstack-deploy-ops-guide/>`__.

NetApp NFS configuration for Data ONTAP operating in 7-Mode
-----------------------------------------------------------

The NetApp NFS configuration for Data ONTAP operating in 7-Mode is an interface
from OpenStack to Data ONTAP operating in 7-Mode storage system for
provisioning and managing OpenStack volumes on NFS exports provided by the Data
ONTAP operating in 7-Mode storage system which can then be accessed using NFS
protocol.

The NFS configuration for Data ONTAP operating in 7-Mode is a direct interface
from Block Storage to the Data ONTAP operating in 7-Mode instance and
as such does not require any additional management software to achieve the
desired functionality. It uses NetApp ONTAPI to interact with the Data ONTAP
operating in 7-Mode storage system.


.. important::
    Support for 7-mode configuration has been deprecated in the Ocata release
    and will be removed in the Queens release of OpenStack.

**Configuration options**

Configure the volume driver, storage family, and storage protocol to the NetApp
unified driver, Data ONTAP operating in 7-Mode, and NFS respectively by setting
the ``volume_driver``, ``netapp_storage_family`` and
``netapp_storage_protocol`` options in the ``cinder.conf`` file as follows:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.netapp.common.NetAppDriver
   netapp_storage_family = ontap_7mode
   netapp_storage_protocol = nfs
   netapp_server_hostname = myhostname
   netapp_server_port = 80
   netapp_login = username
   netapp_password = password
   nfs_shares_config = /etc/cinder/nfs_shares

.. include:: ../../tables/cinder-netapp_7mode_nfs.inc

.. note::

   Additional NetApp NFS configuration options are shared with the
   generic NFS driver. For a description of these, see
   :ref:`cinder-storage_nfs`.

.. tip::

   For more information on these options and other deployment and
   operational scenarios, visit the `NetApp OpenStack Deployment and
   Operations
   Guide <http://netapp.github.io/openstack-deploy-ops-guide/>`__.

NetApp E-Series storage family
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The NetApp E-Series storage family represents a configuration group which
provides OpenStack compute instances access to E-Series storage systems. At
present it can be configured in Block Storage to work with the iSCSI
storage protocol.

NetApp iSCSI configuration for E-Series
---------------------------------------

The NetApp iSCSI configuration for E-Series is an interface from OpenStack to
E-Series storage systems. It provisions and manages the SAN block storage
entity, which is a NetApp LUN which can be accessed using the iSCSI protocol.

The iSCSI configuration for E-Series is an interface from Block
Storage to the E-Series proxy instance and as such requires the deployment of
the proxy instance in order to achieve the desired functionality. The driver
uses REST APIs to interact with the E-Series proxy instance, which in turn
interacts directly with the E-Series controllers.

The use of multipath and DM-MP are required when using the Block
Storage driver for E-Series. In order for Block Storage and OpenStack
Compute to take advantage of multiple paths, the following configuration
options must be correctly configured:

- The ``use_multipath_for_image_xfer`` option should be set to ``True`` in the
  ``cinder.conf`` file within the driver-specific stanza (for example,
  ``[myDriver]``).

- The ``iscsi_use_multipath`` option should be set to ``True`` in the
  ``nova.conf`` file within the ``[libvirt]`` stanza.

**Configuration options**

Configure the volume driver, storage family, and storage protocol to the
NetApp unified driver, E-Series, and iSCSI respectively by setting the
``volume_driver``, ``netapp_storage_family`` and
``netapp_storage_protocol`` options in the ``cinder.conf`` file as follows:

.. code-block:: ini

   volume_driver = cinder.volume.drivers.netapp.common.NetAppDriver
   netapp_storage_family = eseries
   netapp_storage_protocol = iscsi
   netapp_server_hostname = myhostname
   netapp_server_port = 80
   netapp_login = username
   netapp_password = password
   netapp_controller_ips = 1.2.3.4,5.6.7.8
   netapp_sa_password = arrayPassword
   netapp_storage_pools = pool1,pool2
   use_multipath_for_image_xfer = True

.. note::

   To use the E-Series driver, you must override the default value of
   ``netapp_storage_family`` with ``eseries``.

   To use the iSCSI protocol, you must override the default value of
   ``netapp_storage_protocol`` with ``iscsi``.

.. include:: ../../tables/cinder-netapp_eseries_iscsi.inc

.. tip::

   For more information on these options and other deployment and
   operational scenarios, visit the `NetApp OpenStack Deployment and
   Operations
   Guide <http://netapp.github.io/openstack-deploy-ops-guide/>`__.

NetApp-supported extra specs for E-Series
-----------------------------------------

Extra specs enable vendors to specify extra filter criteria.
The Block Storage scheduler uses the specs when the scheduler determines
which volume node should fulfill a volume provisioning request.
When you use the NetApp unified driver with an E-Series storage system,
you can leverage extra specs with Block Storage volume types to ensure
that Block Storage volumes are created on storage back ends that have
certain properties. An example of this is when you configure thin
provisioning for a storage back end.

Extra specs are associated with Block Storage volume types.
When users request volumes of a particular volume type, the volumes are
created on storage back ends that meet the list of requirements.
An example of this is the back ends that have the available space or
extra specs. Use the specs in the following table to configure volumes.
Define Block Storage volume types by using the :command:`openstack volume
type set` command.

.. list-table:: Description of extra specs options for NetApp Unified Driver with E-Series
   :header-rows: 1

   * - Extra spec
     - Type
     - Description
   * - ``netapp_thin_provisioned``
     - Boolean
     - Limit the candidate volume list to only the ones that support thin
       provisioning on the storage controller.

Upgrading prior NetApp drivers to the NetApp unified driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

NetApp introduced a new unified block storage driver in Havana for configuring
different storage families and storage protocols. This requires defining an
upgrade path for NetApp drivers which existed in releases prior to Havana. This
section covers the upgrade configuration for NetApp drivers to the new unified
configuration and a list of deprecated NetApp drivers.

Upgraded NetApp drivers
-----------------------

This section describes how to update Block Storage configuration from
a pre-Havana release to the unified driver format.

-  NetApp iSCSI direct driver for Clustered Data ONTAP in Grizzly (or earlier):

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.netapp.iscsi.NetAppDirectCmodeISCSIDriver

   NetApp unified driver configuration:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.netapp.common.NetAppDriver
      netapp_storage_family = ontap_cluster
      netapp_storage_protocol = iscsi

-  NetApp NFS direct driver for Clustered Data ONTAP in Grizzly (or
   earlier):

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.netapp.nfs.NetAppDirectCmodeNfsDriver

   NetApp unified driver configuration:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.netapp.common.NetAppDriver
      netapp_storage_family = ontap_cluster
      netapp_storage_protocol = nfs

-  NetApp iSCSI direct driver for Data ONTAP operating in 7-Mode storage
   controller in Grizzly (or earlier):

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.netapp.iscsi.NetAppDirect7modeISCSIDriver

   NetApp unified driver configuration:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.netapp.common.NetAppDriver
      netapp_storage_family = ontap_7mode
      netapp_storage_protocol = iscsi

-  NetApp NFS direct driver for Data ONTAP operating in 7-Mode storage
   controller in Grizzly (or earlier):

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.netapp.nfs.NetAppDirect7modeNfsDriver

   NetApp unified driver configuration:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.netapp.common.NetAppDriver
      netapp_storage_family = ontap_7mode
      netapp_storage_protocol = nfs

Deprecated NetApp drivers
-------------------------

This section lists the NetApp drivers in earlier releases that are
deprecated in Havana.

-  NetApp iSCSI driver for clustered Data ONTAP:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.netapp.iscsi.NetAppCmodeISCSIDriver

-  NetApp NFS driver for clustered Data ONTAP:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.netapp.nfs.NetAppCmodeNfsDriver

-  NetApp iSCSI driver for Data ONTAP operating in 7-Mode storage
   controller:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.netapp.iscsi.NetAppISCSIDriver

-  NetApp NFS driver for Data ONTAP operating in 7-Mode storage
   controller:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.netapp.nfs.NetAppNFSDriver

.. note::

   For support information on deprecated NetApp drivers in the Havana
   release, visit the `NetApp OpenStack Deployment and Operations
   Guide <http://netapp.github.io/openstack-deploy-ops-guide/>`__.
