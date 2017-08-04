=======================================
Oracle ZFS Storage Appliance NFS driver
=======================================

The Oracle ZFS Storage Appliance (ZFSSA) NFS driver enables the ZFSSA to
be used seamlessly as a block storage resource. The driver enables you
to to create volumes on a ZFS share that is NFS mounted.

Requirements
~~~~~~~~~~~~

Oracle ZFS Storage Appliance Software version ``2013.1.2.0`` or later.

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, delete, attach, detach, manage, and unmanage volumes.

- Create and delete snapshots.

- Create a volume from a snapshot.

- Extend a volume.

- Copy an image to a volume.

- Copy a volume to an image.

- Clone a volume.

- Volume migration.

- Local cache of a bootable volume

Appliance configuration
~~~~~~~~~~~~~~~~~~~~~~~

Appliance configuration using the command-line interface (CLI) is
described below. To access the CLI, ensure SSH remote access is enabled,
which is the default. You can also perform configuration using the
browser user interface (BUI) or the RESTful API. Please refer to the
`Oracle ZFS Storage Appliance
documentation <http://www.oracle.com/technetwork/documentation/oracle-unified-ss-193371.html>`__
for details on how to configure the Oracle ZFS Storage Appliance using
the BUI, CLI, and RESTful API.

#. Log in to the Oracle ZFS Storage Appliance CLI and enable the REST
   service. REST service needs to stay online for this driver to function.

   .. code-block:: console

      zfssa:>configuration services rest enable

#. Create a new storage pool on the appliance if you do not want to use an
   existing one. This storage pool is named ``'mypool'`` for the sake of this
   documentation.

#. Create a new project and share in the storage pool (``mypool``) if you do
   not want to use existing ones. This driver will create a project and share
   by the names specified in the ``cinder.conf`` file, if a project and share
   by that name does not already exist in the storage pool (``mypool``).
   The project and share are named ``NFSProject`` and ``nfs_share``' in the
   sample ``cinder.conf`` file as entries below.

#. To perform driver operations, create a role with the following
   authorizations:

   .. code-block:: bash

      scope=svc - allow_administer=true, allow_restart=true, allow_configure=true
      scope=nas - pool=pool_name, project=project_name, share=share_name, allow_clone=true, allow_createProject=true, allow_createShare=true, allow_changeSpaceProps=true, allow_changeGeneralProps=true, allow_destroy=true, allow_rollback=true, allow_takeSnap=true, allow_changeAccessProps=true, allow_changeProtocolProps=true

   The following examples show how to create a role with authorizations.

   .. code-block:: console

      zfssa:> configuration roles
      zfssa:configuration roles> role OpenStackRole
      zfssa:configuration roles OpenStackRole (uncommitted)> set description="OpenStack NFS Cinder Driver"
      zfssa:configuration roles OpenStackRole (uncommitted)> commit
      zfssa:configuration roles> select OpenStackRole
      zfssa:configuration roles OpenStackRole> authorizations create
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set scope=svc
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_administer=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_restart=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_configure=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> commit


   .. code-block:: console

      zfssa:> configuration roles OpenStackRole authorizations> set scope=nas

   The following properties need to be set when the scope of this role needs to
   be limited to a pool (``mypool``), a project (``NFSProject``) and a share
   (``nfs_share``) created in the steps above. This will prevent the user
   assigned to this role from being used to modify other pools, projects and
   shares.

   .. code-block:: console

      zfssa:configuration roles OpenStackRole auth (uncommitted)> set pool=mypool
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set project=NFSProject
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set share=nfs_share

#. The following properties only need to be set when a share and project has
   not been created following the steps above and wish to allow the driver to
   create them for you.

   .. code-block:: console

      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_createProject=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_createShare=true

   .. code-block:: console

      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_clone=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_changeSpaceProps=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_destroy=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_rollback=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_takeSnap=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_changeAccessProps=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> set allow_changeProtocolProps=true
      zfssa:configuration roles OpenStackRole auth (uncommitted)> commit

#. Create a new user or modify an existing one and assign the new role to
   the user.

   The following example shows how to create a new user and assign the new
   role to the user.

   .. code-block:: console

      zfssa:> configuration users
      zfssa:configuration users> user cinder
      zfssa:configuration users cinder (uncommitted)> set fullname="OpenStack Cinder Driver"
      zfssa:configuration users cinder (uncommitted)> set initial_password=12345
      zfssa:configuration users cinder (uncommitted)> commit
      zfssa:configuration users> select cinder set roles=OpenStackRole

#. Ensure that NFS and HTTP services on the appliance are online. Note the
   HTTPS port number for later entry in the cinder service configuration file
   (``cinder.conf``). This driver uses WebDAV over HTTPS to create snapshots
   and clones of volumes, and therefore needs to have the HTTP service online.

   The following example illustrates enabling the services and showing their
   properties.

   .. code-block:: console

      zfssa:> configuration services nfs
      zfssa:configuration services nfs> enable
      zfssa:configuration services nfs> show
      Properties:
      <status>= online
      ...

   .. code-block:: console

      zfssa:configuration services http> enable
      zfssa:configuration services http> show
      Properties:
      <status>= online
      require_login = true
      protocols = http/https
      listen_port = 80
      https_port = 443

   .. note::

      You can also run this `workflow
      <https://openstackci.oracle.com/openstack_docs/zfssa_cinder_workflow.akwf>`__
      to automate the above tasks.
      Refer to `Oracle documentation
      <https://docs.oracle.com/cd/E37831_01/html/E52872/godgw.html>`__
      on how to download, view, and execute a workflow.

#. Create a network interface to be used exclusively for data. An existing
   network interface may also be used. The following example illustrates how to
   make a network interface for data traffic flow only.

   .. note::

      For better performance and reliability, it is recommended to configure a
      separate subnet exclusively for data traffic in your cloud environment.

   .. code-block:: console

      zfssa:> configuration net interfaces
      zfssa:configuration net interfaces> select igbx
      zfssa:configuration net interfaces igbx> set admin=false
      zfssa:configuration net interfaces igbx> commit

#. For clustered controller systems, the following verification is required in
   addition to the above steps. Skip this step if a standalone system is used.

   .. code-block:: console

      zfssa:> configuration cluster resources list

   Verify that both the newly created pool and the network interface are of
   type ``singleton`` and are not locked to the current controller.  This
   approach ensures that the pool and the interface used for data always belong
   to the active controller, regardless of the current state of the cluster.
   Verify that both the network interface used for management and data, and the
   storage pool belong to the same head.

   .. note::

      There will be a short service interruption during failback/takeover, but
      once the process is complete, the driver should be able to access the
      ZFSSA for data as well as for management.

Cinder service configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Define the following required properties in the ``cinder.conf``
   configuration file:

   .. code-block:: ini

      volume_driver = cinder.volume.drivers.zfssa.zfssanfs.ZFSSANFSDriver
      san_ip = myhost
      san_login = username
      san_password = password
      zfssa_data_ip = mydata
      zfssa_nfs_pool = mypool

   .. note::

      Management interface ``san_ip`` can be used instead of ``zfssa_data_ip``,
      but it is not recommended.

#. You can also define the following additional properties in the
   ``cinder.conf`` configuration file:

   .. code:: ini

       zfssa_nfs_project = NFSProject
       zfssa_nfs_share = nfs_share
       zfssa_nfs_mount_options =
       zfssa_nfs_share_compression = off
       zfssa_nfs_share_logbias = latency
       zfssa_https_port = 443

   .. note::

      The driver does not use the file specified in the ``nfs_shares_config``
      option.

ZFSSA local cache
~~~~~~~~~~~~~~~~~

The local cache feature enables ZFSSA drivers to serve the usage of
bootable volumes significantly better. With the feature, the first
bootable volume created from an image is cached, so that subsequent
volumes can be created directly from the cache, instead of having image
data transferred over the network multiple times.

The following conditions must be met in order to use ZFSSA local cache
feature:

-  A storage pool needs to be configured.

-  REST and NFS services need to be turned on.

-  On an OpenStack controller, ``cinder.conf`` needs to contain
   necessary properties used to configure and set up the ZFSSA NFS
   driver, including the following new properties:

   zfssa_enable_local_cache
        (True/False) To enable/disable the feature.

   zfssa_cache_directory
        The directory name inside zfssa_nfs_share where cache volumes
        are stored.

Every cache volume has two additional properties stored as WebDAV
properties. It is important that they are not altered outside of Block
Storage when the driver is in use:

image_id
  stores the image id as in Image service.

updated_at
  stores the most current timestamp when the image is
  updated in Image service.

Driver options
~~~~~~~~~~~~~~

The Oracle ZFS Storage Appliance NFS driver supports these options:

.. include:: ../../tables/cinder-zfssa-nfs.inc

This driver shares additional NFS configuration options with the generic
NFS driver. For a description of these, see :ref:`cinder-storage_nfs`.
