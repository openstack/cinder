.. _windows_smb_volume_driver:

=========================
Windows SMB volume driver
=========================

Description
~~~~~~~~~~~

The Windows SMB volume driver leverages pre-existing SMB shares, used to store
volumes as virtual disk images.

The main reasons to use the Windows SMB driver are:

* ease of management and use
* great integration with other Microsoft technologies (e.g. Hyper-V Failover
  Cluster)
* suitable for a various range of deployment types and sizes

The ``cinder-volume`` service as well as the required Python components will
be installed directly onto designated Windows nodes (prefferably the ones
exposing the shares).

Common deployment scenarios
---------------------------

The SMB driver is designed to support a variety of scenarios, such as:

* Scale-Out File Servers (``SoFS``), providing highly available SMB shares.
* standalone Windows or Samba shares
* any other SMB 3.0 capable device

By using SoFS shares, the virtual disk images are stored on Cluster Shared
Volumes (``CSV``).

A common practice involves depoying CSVs on top of SAN backed LUNs
(exposed to all the nodes of the cluster through iSCSI or Fibre Channel). In
absence of a SAN, Storage Spaces/Storage Spaces Direct (``S2D``) may be used
for the underlying storage.

.. note::

   S2D is commonly used in hyper-converged deployments.
.. end

Features
--------

``VHD`` and ``VHDX`` are the currently supported image formats and may be
consumed by Hyper-V and KVM compute nodes. By default, dynamic (thinly
provisioned) images will be used, unless configured otherwise.

The driver accepts one or more shares that will be reported to the Cinder
scheduler as storage pools. This can provide means of tiering, allowing
specific shares (pools) to be requested through volume types.

.. code-block:: console

   openstack volume type set $volume_type --property pool_name=$pool_name
.. end

Frontend QoS specs may be associated with the volume types and enforced on the
consumer side (e.g. Hyper-V).

.. code-block:: console

   openstack volume qos create $rule_name --property consumer=front-end --property total_bytes_sec=20971520
   openstack volume qos associate $rule_name $volume_type_id
   openstack volume create $volume_name --type $volume_type_id --size $size
.. end

The ``Cinder Backup Service`` can be run on Windows. This driver stores
the volumes using vhdx images stored on SMB shares which can be attached
in order to retrieve the volume data and send it to the backup service.

Prerequisites:

* All physical disks must be in byte mode
* rb+ must be used when writing backups to disk

Clustering support
------------------
Active-Active Cinder clustering is currently experimental and should not be
used in production. This implies having multiple Cinder Volume services
handling the same share simultaneously.

On the other hand, Active-Pasive clustering can easily be achieved, configuring
the Cinder Volume service as clustered using Microsoft Failover Cluster.

By using SoFS, you can provide high availability of the shares used by Cinder.
This can be used in conjunction with the Nova Hyper-V cluster driver, which
allows clustering virtual machines. This ensures that when a compute node is
compromised, the virtual machines are transparently migrated to a healthy
node, preserving volume connectivity.

.. note::

   The Windows SMB driver is the only Cinder driver that may be used along
   with the Nova Hyper-V cluster driver. The reason is that during an
   unexpected failover, the volumes need to be available on the destination
   compute node side.


.. _windows_smb_volume_driver_prerequisites:

Prerequisites
~~~~~~~~~~~~~

Before setting up the SMB driver, you will need to create and configure one or
more SMB shares that will be used for storing virtual disk images.

.. note::
   The driver does not manage share permissions. You will have to make sure
   that Cinder as well as share consumers (e.g. Nova, Hyper-V) have access.

   Note that Hyper-V VMs are run using a built-in user group:
   ``NT VIRTUAL MACHINE\Virtual Machines``.
.. end

The easiest way to provide share access is by using Active Directory accounts.
You may grant share access to the users running OpenStack services, as well as
the compute nodes (and optionally storage nodes), using per computer account
access rules. One of the main advantages is that by doing so, you don't need
to pass share credentials to Cinder (and implicitly volume consumers).

By granting access to a computer account, you're basically granting access to
the LocalSystem account of that node, and thus to the VMs running on that
host.

.. note::
    By default, OpenStack services deployed using the MSIs are run as
    LocalSystem.

Once you've granted share access to a specific account, don't forget to also
configure file system level permissions on the directory exported by the
share.

Configuring cinder-volume
~~~~~~~~~~~~~~~~~~~~~~~~~

Below is a configuration sample for using the Windows SMB Driver. Append
those options to your already existing ``cinder.conf`` file, described at
:ref:`cinder_storage_install_windows`.

.. code-block:: ini

   [DEFAULT]
   enabled_backends = winsmb

   [winsmb]
   volume_backend_name = myWindowsSMBBackend
   volume_driver = cinder.volume.drivers.windows.smbfs.WindowsSmbfsDriver
   smbfs_mount_point_base = C:\OpenStack\mnt\
   smbfs_shares_config = C:\Program Files\Cloudbase Solutions\OpenStack\etc\cinder\smbfs_shares_list

   # The following config options are optional
   #
   # image_volume_cache_enabled = true
   # image_volume_cache_max_size_gb = 100
   # image_volume_cache_max_count = 10
   #
   # nas_volume_prov_type = thin
   # smbfs_default_volume_format = vhdx
   # max_over_subscription_ratio = 1.5
   # reserved_percentage = 5
   # smbfs_pool_mappings = //addr/share:pool_name,//addr/share2:pool_name2
.. end

The ``smbfs_mount_point_base`` config option allows you to specify where
the shares will be *mounted*. This directory will contain symlinks pointing
to the shares used by Cinder. Each symlink name will be a hash of the actual
share path.

Configuring the list of available shares
----------------------------------------

In addition to ``cinder.conf``, you will need to have another config file,
providing a list of shares that will be used by Cinder for storing disk
images. In the above sample, this file is referenced by the
``smbfs_shares_config`` option.

The share list config file must contain one share per line, optionally
including mount options. You may also add comments, using a '#' at the
beginning of the line.

Bellow is a sample of the share list config file:

.. code-block:: ini

   # Cinder Volume shares
   //sofs-cluster/share
   //10.0.0.10/volumes -o username=user,password=mypassword
.. end

Keep in mind that Linux hosts can also consume those volumes. For this
reason, the mount options resemble the ones used by mount.cifs (in fact,
those will actually be passed to mount.cifs by the Nova Linux nodes).

In case of Windows nodes, only the share location, username and password
will be used when mounting the shares. The share address must use slashes
instead of backslashes (as opposed to what Windows admins may expect) because
of the above mentioned reason.

Depending on the configured share access rules, you may skip including
share credentials in the config file, as described in the
:ref:`windows_smb_volume_driver_prerequisites` section.

Configuring Nova credentials
----------------------------

The SMB volume driver relies on the ``nova assisted volume snapshots`` feature
when snapshotting in-use volumes, as do other similar drivers using shared
filesystems.

By default, the Nova policy requires admin rights for this operation. You may
provide Cinder specific credentials to be used when requesting Nova assisted
volume snapshots, as shown bellow:

.. code-block:: ini

   [nova]
   region_name=RegionOne
   auth_strategy=keystone
   auth_type=password
   auth_url=http://keystone_host/identity
   project_name=service
   username=nova
   password=password
   project_domain_name=Default
   user_domain_name=Default
.. end

Configuring storage pools
-------------------------

Each share is reported to the Cinder scheduler as a storage pool.

By default, the share name will be the name of the pool. If needed, you may
provide pool name mappings, specifying a custom pool name for each share,
as shown bellow:

.. code-block:: ini

   smbfs_pool_mappings = //addr/share:pool0
.. end

In the above sample, the ``//addr/share`` share will be reported as ``pool0``.

