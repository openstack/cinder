========================================================
Kaminario K2 all-flash array iSCSI and FC volume drivers
========================================================

Kaminario's K2 all-flash array leverages a unique software-defined
architecture that delivers highly valued predictable performance, scalability
and cost-efficiency.

Kaminario's K2 all-flash iSCSI and FC arrays can be used in
OpenStack Block Storage for providing block storage using
``KaminarioISCSIDriver`` class and ``KaminarioFCDriver`` class respectively.

This documentation explains how to configure and connect the block storage
nodes to one or more K2 all-flash arrays.

Driver requirements
~~~~~~~~~~~~~~~~~~~

- Kaminario's K2 all-flash iSCSI and/or FC array

- K2 REST API version >= 2.2.0

- K2 version 5.8 or later are supported

- ``krest`` python library(version 1.3.1 or later) should be installed on the
  Block Storage node using :command:`sudo pip install krest`

- The Block Storage Node should also have a data path to the K2 array
  for the following operations:

  - Create a volume from snapshot
  - Clone a volume
  - Copy volume to image
  - Copy image to volume
  - Retype 'dedup without replication'<->'nodedup without replication'

Supported operations
~~~~~~~~~~~~~~~~~~~~~

- Create, delete, attach, and detach volumes.
- Create and delete volume snapshots.
- Create a volume from a snapshot.
- Copy an image to a volume.
- Copy a volume to an image.
- Clone a volume.
- Extend a volume.
- Retype a volume.
- Manage and unmanage a volume.
- Replicate volume with failover and failback support to K2 array.

Limitations and known issues
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If your OpenStack deployment is not setup to use multipath, the network
connectivity of the K2 all-flash array will use a single physical port.

This may significantly limit the following benefits provided by K2:

- available bandwidth
- high-availability
- non disruptive-upgrade

The following steps are required to setup multipath access on the
Compute and the Block Storage nodes

#. Install multipath software on both Compute and Block Storage nodes.

   For example:

   .. code-block:: console

      # apt-get install sg3-utils multipath-tools

#. In the ``[libvirt]`` section of the ``nova.conf`` configuration file,
   specify ``iscsi_use_multipath=True``. This option is valid for both iSCSI
   and FC drivers.

   Additional resources: Kaminario Host Configuration Guide
   for Linux (for configuring multipath)

#. Restart the compute service for the changes to take effect.

   .. code-block:: console

      # service nova-compute restart


Configure single Kaminario iSCSI/FC back end
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section details the steps required to configure the Kaminario
Cinder Driver for single FC or iSCSI backend.

#. In the ``cinder.conf`` configuration file under the ``[DEFAULT]``
   section, set the  ``scheduler_default_filters`` parameter:

   .. code-block:: ini

      [DEFAULT]
      scheduler_default_filters = DriverFilter,CapabilitiesFilter

   See following links for more information:
   `<https://docs.openstack.org/developer/cinder/scheduler-filters.html>`_
   `<https://docs.openstack.org/admin-guide/blockstorage-driver-filter-weighing.html>`_

#. Under the ``[DEFAULT]`` section, set the enabled_backends parameter
   with the iSCSI or FC back-end group

   .. code-block:: ini

      [DEFAULT]
      # For iSCSI
      enabled_backends = kaminario-iscsi-1

      # For FC
      # enabled_backends = kaminario-fc-1

#. Add a back-end group section for back-end group specified
   in the enabled_backends parameter

#. In the newly created back-end group section, set the
   following configuration options:

   .. code-block:: ini

      [kaminario-iscsi-1]
      # Management IP of Kaminario K2 All-Flash iSCSI/FC array
      san_ip = 10.0.0.10
      # Management username of Kaminario K2 All-Flash iSCSI/FC array
      san_login = username
      # Management password of Kaminario K2 All-Flash iSCSI/FC array
      san_password = password
      # Enable Kaminario K2 iSCSI/FC driver
      volume_driver = cinder.volume.drivers.kaminario.kaminario_iscsi.KaminarioISCSIDriver
      # volume_driver = cinder.volume.drivers.kaminario.kaminario_fc.KaminarioFCDriver

      # Backend name
      # volume_backend_name = kaminario_fc_1
      volume_backend_name = kaminario_iscsi_1

      # K2 driver calculates max_oversubscription_ratio on setting below
      # option as True. Default value is False
      # auto_calc_max_oversubscription_ratio = False

      # Set a limit on total number of volumes to be created on K2 array, for example:
      # filter_function = "capabilities.total_volumes < 250"

      # For replication, replication_device must be set and the replication peer must be configured
      # on the primary and the secondary K2 arrays
      # Syntax:
      #     replication_device = backend_id:<s-array-ip>,login:<s-username>,password:<s-password>,rpo:<value>
      # where:
      #     s-array-ip is the secondary K2 array IP
      #     rpo must be either 60(1 min) or multiple of 300(5 min)
      # Example:
      # replication_device = backend_id:10.0.0.50,login:kaminario,password:kaminario,rpo:300

      # Suppress requests library SSL certificate warnings on setting this option as True
      # Default value is 'False'
      # suppress_requests_ssl_warnings = False

#. Restart the Block Storage services for the changes to take effect:

   .. code-block:: console

      # service cinder-api restart
      # service cinder-scheduler restart
      # service cinder-volume restart

Setting multiple Kaminario iSCSI/FC back ends
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following steps are required to configure multiple K2 iSCSI/FC backends:

#. In the :file:`cinder.conf` file under the [DEFAULT] section,
   set the enabled_backends parameter with the comma-separated
   iSCSI/FC back-end groups.

   .. code-block:: ini

      [DEFAULT]
      enabled_backends = kaminario-iscsi-1, kaminario-iscsi-2, kaminario-iscsi-3

#. Add a back-end group section for each back-end group specified
   in the enabled_backends parameter

#. For each back-end group section, enter the configuration options as
   described in the above section
   ``Configure single Kaminario iSCSI/FC back end``

   See `Configure multiple-storage back ends
   <https://docs.openstack.org/admin-guide/blockstorage-multi-backend.html>`__
   for additional information.

#. Restart the cinder volume service for the changes to take effect.

   .. code-block:: console

      # service cinder-volume restart

Creating volume types
~~~~~~~~~~~~~~~~~~~~~

Create volume types for supporting volume creation on
the multiple K2 iSCSI/FC backends.
Set following extras-specs in the volume types:

- volume_backend_name : Set value of this spec according to the
  value of ``volume_backend_name`` in the back-end group sections.
  If only this spec is set, then dedup Kaminario cinder volumes will be
  created without replication support

  .. code-block:: console

     $ openstack volume type create kaminario_iscsi_dedup_noreplication
     $ openstack volume type set --property volume_backend_name=kaminario_iscsi_1 \
       kaminario_iscsi_dedup_noreplication

- kaminario:thin_prov_type :  Set this spec in the volume type for creating
  nodedup Kaminario cinder volumes. If this spec is not set, dedup Kaminario
  cinder volumes will be created.

- kaminario:replication : Set this spec in the volume type for creating
  replication supported Kaminario cinder volumes. If this spec is not set,
  then Kaminario cinder volumes will be created without replication support.

  .. code-block:: console

     $ openstack volume type create kaminario_iscsi_dedup_replication
     $ openstack volume type set --property volume_backend_name=kaminario_iscsi_1 \
       kaminario:replication=enabled kaminario_iscsi_dedup_replication

     $ openstack volume type create kaminario_iscsi_nodedup_replication
     $ openstack volume type set --property volume_backend_name=kaminario_iscsi_1 \
       kaminario:replication=enabled kaminario:thin_prov_type=nodedup \
       kaminario_iscsi_nodedup_replication

     $ openstack volume type create kaminario_iscsi_nodedup_noreplication
     $ openstack volume type set --property volume_backend_name=kaminario_iscsi_1 \
       kaminario:thin_prov_type=nodedup kaminario_iscsi_nodedup_noreplication

Supported retype cases
~~~~~~~~~~~~~~~~~~~~~~
The following are the supported retypes for Kaminario cinder volumes:

- Nodedup-noreplication <--> Nodedup-replication

  .. code-block:: console

     $ cinder retype volume-id new-type

- Dedup-noreplication <--> Dedup-replication

  .. code-block:: console

     $ cinder retype volume-id new-type

- Dedup-noreplication <--> Nodedup-noreplication

  .. code-block:: console

     $ cinder retype --migration-policy on-demand volume-id new-type

For non-supported cases, try combinations of the
:command:`cinder retype` command.

Driver options
~~~~~~~~~~~~~~

The following table contains the configuration options that are specific
to the Kaminario K2 FC and iSCSI Block Storage drivers.

.. include:: ../../tables/cinder-kaminario.inc
