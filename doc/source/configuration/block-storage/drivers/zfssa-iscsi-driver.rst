=========================================
Oracle ZFS Storage Appliance iSCSI driver
=========================================

Oracle ZFS Storage Appliances (ZFSSAs) provide advanced software to
protect data, speed tuning and troubleshooting, and deliver high
performance and high availability. Through the Oracle ZFSSA iSCSI
Driver, OpenStack Block Storage can use an Oracle ZFSSA as a block
storage resource. The driver enables you to create iSCSI volumes that an
OpenStack Block Storage server can allocate to any virtual machine
running on a compute host.

Requirements
~~~~~~~~~~~~

The Oracle ZFSSA iSCSI Driver, version ``1.0.0`` and later, supports
ZFSSA software release ``2013.1.2.0`` and later.

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, delete, attach, detach, manage, and unmanage volumes.
- Create and delete snapshots.
- Create volume from snapshot.
- Extend a volume.
- Attach and detach volumes.
- Get volume stats.
- Clone volumes.
- Migrate a volume.
- Local cache of a bootable volume.

Configuration
~~~~~~~~~~~~~

#. Enable RESTful service on the ZFSSA Storage Appliance.

#. Create a new user on the appliance with the following authorizations:

   .. code-block:: bash

      scope=stmf - allow_configure=true
      scope=nas - allow_clone=true, allow_createProject=true, allow_createShare=true, allow_changeSpaceProps=true, allow_changeGeneralProps=true, allow_destroy=true, allow_rollback=true, allow_takeSnap=true
      scope=schema - allow_modify=true

   You can create a role with authorizations as follows:

   .. code-block:: console

      zfssa:> configuration roles
      zfssa:configuration roles> role OpenStackRole
      zfssa:configuration roles OpenStackRole (uncommitted)> set description="OpenStack Cinder Driver"
      zfssa:configuration roles OpenStackRole (uncommitted)> commit
      zfssa:configuration roles> select OpenStackRole
      zfssa:configuration roles OpenStackRole> authorizations create
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set scope=stmf
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_configure=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> commit
      zfssa:configuration roles OpenStackRole> authorizations create
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set scope=nas
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_clone=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_createProject=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_createShare=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_changeSpaceProps=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_changeGeneralProps=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_destroy=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_rollback=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_takeSnap=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> commit

   You can create a user with a specific role as follows:

   .. code-block:: console

      zfssa:> configuration users
      zfssa:configuration users> user cinder
      zfssa:configuration users cinder (uncommitted)> set fullname="OpenStack Cinder Driver"
      zfssa:configuration users cinder (uncommitted)> set initial_password=12345
      zfssa:configuration users cinder (uncommitted)> commit
      zfssa:configuration users> select cinder set roles=OpenStackRole

   .. note::

      You can also run this `workflow
      <https://openstackci.oracle.com/openstack_docs/zfssa_cinder_workflow.akwf>`__
      to automate the above tasks.
      Refer to `Oracle documentation
      <https://docs.oracle.com/cd/E37831_01/html/E52872/godgw.html>`__
      on how to download, view, and execute a workflow.

#. Ensure that the ZFSSA iSCSI service is online. If the ZFSSA iSCSI service is
   not online, enable the service by using the BUI, CLI or REST API in the
   appliance.

   .. code-block:: console

      zfssa:> configuration services iscsi
      zfssa:configuration services iscsi> enable
      zfssa:configuration services iscsi> show
      Properties:
      <status>= online
      ...

   Define the following required properties in the ``cinder.conf`` file:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.zfssa.zfssaiscsi.ZFSSAISCSIDriver
      san_ip = myhost
      san_login = username
      san_password = password
      zfssa_pool = mypool
      zfssa_project = myproject
      zfssa_initiator_group = default
      zfssa_target_portal = w.x.y.z:3260
      zfssa_target_interfaces = e1000g0

   Optionally, you can define additional properties.

   Target interfaces can be seen as follows in the CLI:

   .. code-block:: console

      zfssa:> configuration net interfaces
      zfssa:configuration net interfaces> show
      Interfaces:
      INTERFACE STATE CLASS LINKS    ADDRS          LABEL
      e1000g0   up    ip    e1000g0  1.10.20.30/24  Untitled Interface
      ...

   .. note::

      Do not use management interfaces for ``zfssa_target_interfaces``.

#. Configure the cluster:

   If a cluster is used as the cinder storage resource, the following
   verifications are required on your Oracle ZFS Storage Appliance:

   - Verify that both the pool and the network interface are of type
     singleton and are not locked to the current controller. This
     approach ensures that the pool and the interface used for data
     always belong to the active controller, regardless of the current
     state of the cluster.

   - Verify that the management IP, data IP and storage pool belong to
     the same head.

   .. note::

      Most configuration settings, including service properties, users, roles,
      and iSCSI initiator definitions are replicated on both heads
      automatically. If the driver modifies any of these settings, they will be
      modified automatically on both heads.

   .. note::

      A short service interruption occurs during failback or takeover,
      but once the process is complete, the ``cinder-volume`` service should be able
      to access the pool through the data IP.

ZFSSA assisted volume migration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ZFSSA iSCSI driver supports storage assisted volume migration
starting in the Liberty release. This feature uses remote replication
feature on the ZFSSA. Volumes can be migrated between two backends
configured not only to the same ZFSSA but also between two separate
ZFSSAs altogether.

The following conditions must be met in order to use ZFSSA assisted
volume migration:

- Both the source and target backends are configured to ZFSSAs.

- Remote replication service on the source and target appliance is enabled.

- The ZFSSA to which the target backend is configured should be configured as a
  target in the remote replication service of the ZFSSA configured to the
  source backend. The remote replication target needs to be configured even
  when the source and the destination for volume migration are the same ZFSSA.
  Define ``zfssa_replication_ip`` in the ``cinder.conf`` file of the source
  backend as the IP address used to register the target ZFSSA in the remote
  replication service of the source ZFSSA.

- The name of the iSCSI target group(``zfssa_target_group``) on the source and
  the destination ZFSSA is the same.

- The volume is not attached and is in available state.

If any of the above conditions are not met, the driver will proceed with
generic volume migration.

The ZFSSA user on the source and target appliances will need to have
additional role authorizations for assisted volume migration to work. In
scope nas, set ``allow_rrtarget`` and ``allow_rrsource`` to ``true``.

.. code-block:: console

   zfssa:configuration roles OpenStackRole auth (uncommitted)> set scope=nas
   zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_rrtarget=true
   zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_rrsource=true

ZFSSA local cache
~~~~~~~~~~~~~~~~~

The local cache feature enables ZFSSA drivers to serve the usage of bootable
volumes significantly better. With the feature, the first bootable volume
created from an image is cached, so that subsequent volumes can be created
directly from the cache, instead of having image data transferred over the
network multiple times.

The following conditions must be met in order to use ZFSSA local cache feature:

- A storage pool needs to be configured.

- REST and iSCSI services need to be turned on.

- On an OpenStack controller, ``cinder.conf`` needs to contain necessary
  properties used to configure and set up the ZFSSA iSCSI driver, including the
  following new properties:

  - ``zfssa_enable_local_cache``: (True/False) To enable/disable the feature.

  - ``zfssa_cache_project``: The ZFSSA project name where cache volumes are
    stored.

Every cache volume has two additional properties stored as ZFSSA custom
schema. It is important that the schema are not altered outside of Block
Storage when the driver is in use:

- ``image_id``: stores the image id as in Image service.

- ``updated_at``: stores the most current timestamp when the image is updated
  in Image service.

Supported extra specs
~~~~~~~~~~~~~~~~~~~~~

Extra specs provide the OpenStack storage admin the flexibility to create
volumes with different characteristics from the ones specified in the
``cinder.conf`` file. The admin will specify the volume properties as keys
at volume type creation. When a user requests a volume of this volume type,
the volume will be created with the properties specified as extra specs.

The following extra specs scoped keys are supported by the driver:

-  ``zfssa:volblocksize``

-  ``zfssa:sparse``

-  ``zfssa:compression``

-  ``zfssa:logbias``

Volume types can be created using the :command:`openstack volume type create`
command.
Extra spec keys can be added using :command:`openstack volume type set`
command.

Driver options
~~~~~~~~~~~~~~

The Oracle ZFSSA iSCSI Driver supports these options:

.. include:: ../../tables/cinder-zfssa-iscsi.inc
