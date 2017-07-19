==========================================
Hitachi NAS Platform NFS driver
==========================================

This OpenStack Block Storage volume drivers provides NFS support
for `Hitachi NAS Platform (HNAS) <http://www.hds.com/products/file-and-content/
network-attached-storage/>`_ Models 3080, 3090, 4040, 4060, 4080, and 4100
with NAS OS 12.2 or higher.

Supported operations
~~~~~~~~~~~~~~~~~~~~

The NFS driver support these operations:

* Create, delete, attach, and detach volumes.
* Create, list, and delete volume snapshots.
* Create a volume from a snapshot.
* Copy an image to a volume.
* Copy a volume to an image.
* Clone a volume.
* Extend a volume.
* Get volume statistics.
* Manage and unmanage a volume.
* Manage and unmanage snapshots (`HNAS NFS only`).
* List manageable volumes and snapshots (`HNAS NFS only`).

HNAS storage requirements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Before using NFS services, use the HNAS configuration and management
GUI (SMU) or SSC CLI to configure HNAS to work with the drivers. Additionally:

1. General:

* It is mandatory to have at least ``1 storage pool, 1 EVS and 1 file
  system`` to be able to run any of the HNAS drivers.
* HNAS drivers consider the space allocated to the file systems to
  provide the reports to cinder. So, when creating a file system, make sure
  it has enough space to fit your needs.
* The file system used should not be created as a ``replication target`` and
  should be mounted.
* It is possible to configure HNAS drivers to use distinct EVSs and file
  systems, but ``all compute nodes and controllers`` in the cloud must have
  access to the EVSs.

2. For NFS:

* Create NFS exports, choose a path for them (it must be different from
  ``/``) and set the :guilabel: `Show snapshots` option to ``hide and
  disable access``.
* For each export used, set the option ``norootsquash`` in the share
  ``Access configuration`` so Block Storage services can change the
  permissions of its volumes. For example, ``"* (rw, norootsquash)"``.
* Make sure that all computes and controllers have R/W access to the
  shares used by cinder HNAS driver.
* In order to use the hardware accelerated features of HNAS NFS, we
  recommend setting ``max-nfs-version`` to 3. Refer to Hitachi NAS Platform
  command line reference to see how to configure this option.

Block Storage host requirements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The HNAS drivers are supported for Red Hat Enterprise Linux OpenStack
Platform, SUSE OpenStack Cloud, and Ubuntu OpenStack.
The following packages must be installed in all compute, controller and
storage (if any) nodes:

* ``nfs-utils`` for Red Hat Enterprise Linux OpenStack Platform
* ``nfs-client`` for SUSE OpenStack Cloud
* ``nfs-common``, ``libc6-i386`` for Ubuntu OpenStack

Package installation
--------------------

If you are installing the driver from an RPM or DEB package,
follow the steps below:

#. Install the dependencies:

   In Red Hat:

   .. code-block:: console

      # yum install nfs-utils nfs-utils-lib

   Or in Ubuntu:

   .. code-block:: console

      # apt-get install nfs-common

   Or in SUSE:

   .. code-block:: console

      # zypper install nfs-client

   If you are using Ubuntu 12.04, you also need to install ``libc6-i386``

   .. code-block:: console

     # apt-get install libc6-i386

#. Configure the driver as described in the :ref:`hnas-driver-configuration`
   section.

#. Restart all Block Storage services (volume, scheduler, and backup).

.. _hnas-driver-configuration:

Driver configuration
~~~~~~~~~~~~~~~~~~~~

HNAS supports a variety of storage options and file system capabilities,
which are selected through the definition of volume types combined with the
use of multiple back ends and multiple services. Each back end can configure
up to ``4 service pools``, which can be mapped to cinder volume types.

The configuration for the driver is read from the back-end sections of the
``cinder.conf``. Each back-end section must have the appropriate configurations
to communicate with your HNAS back end, such as the IP address of the HNAS EVS
that is hosting your data, HNAS SSH access credentials, the configuration of
each of the services in that back end, and so on. You can find examples of such
configurations in the :ref:`configuration_example` section.

.. note::
  HNAS cinder drivers still support the XML configuration the
  same way it was in the older versions, but we recommend configuring the
  HNAS cinder drivers only through the ``cinder.conf`` file,
  since the XML configuration file from previous versions is being
  deprecated as of Newton Release.

.. note::
  We do not recommend the use of the same NFS export for different back ends.
  If possible, configure each back end to
  use a different NFS export/file system.

The following is the definition of each configuration option that can be used
in a HNAS back-end section in the ``cinder.conf`` file:

.. list-table:: **Configuration options in cinder.conf**
   :header-rows: 1
   :widths: 25, 10, 15, 50

   * - Option
     - Type
     - Default
     - Description
   * - ``volume_backend_name``
     - Optional
     - N/A
     - A name that identifies the back end and can be used as an extra-spec to
       redirect the volumes to the referenced back end.
   * - ``volume_driver``
     - Required
     - N/A
     - The python module path to the HNAS volume driver python class. When
       installing through the rpm or deb packages, you should configure this
       to `cinder.volume.drivers.hitachi.hnas_nfs.HNASNFSDriver`.
   * - ``nfs_shares_config``
     - Required (only for NFS)
     - /etc/cinder/nfs_shares
     - Path to the ``nfs_shares`` file. This is required by the base cinder
       generic NFS driver and therefore also required by the HNAS NFS driver.
       This file should list, one per line, every NFS share being used by the
       back end. For example, all the values found in the configuration keys
       hnas_svcX_hdp in the HNAS NFS back-end sections.
   * - ``hnas_mgmt_ip0``
     - Required
     - N/A
     - HNAS management IP address. Should be the IP address of the `Admin`
       EVS. It is also the IP through which you access the web SMU
       administration frontend of HNAS.
   * - ``hnas_username``
     - Required
     - N/A
     - HNAS SSH username
   * - ``hds_hnas_nfs_config_file``
     - Optional (deprecated)
     - /opt/hds/hnas/cinder_nfs_conf.xml
     - Path to the deprecated XML configuration file (only required if using
       the XML file)
   * - ``hnas_cluster_admin_ip0``
     - Optional (required only for HNAS multi-farm setups)
     - N/A
     - The IP of the HNAS farm admin. If your SMU controls more than one
       system or cluster, this option must be set with the IP of the desired
       node. This is different for HNAS multi-cluster setups, which
       does not require this option to be set.
   * - ``hnas_ssh_private_key``
     - Optional
     - N/A
     - Path to the SSH private key used to authenticate to the HNAS SMU. Only
       required if you do not want to set `hnas_password`.
   * - ``hnas_ssh_port``
     - Optional
     - 22
     - Port on which HNAS is listening for SSH connections
   * - ``hnas_password``
     - Required (unless hnas_ssh_private_key is provided)
     - N/A
     - HNAS password
   * - ``hnas_svcX_hdp`` [1]_
     - Required (at least 1)
     - N/A
     - HDP (export) where the volumes will be created. Use
       exports paths to configure this.
   * - ``hnas_svcX_pool_name``
     - Required
     - N/A
     - A `unique string` that is used to refer to this pool within the
       context of cinder. You can tell cinder to put volumes of a specific
       volume type into this back end, within this pool. See,
       ``Service Labels`` and :ref:`configuration_example` sections
       for more details.

.. [1]
   Replace X with a number from 0 to 3 (keep the sequence when configuring
   the driver)

Service labels
~~~~~~~~~~~~~~

HNAS driver supports differentiated types of service using the service labels.
It is possible to create up to 4 types of them for each back end. (For example
gold, platinum, silver, ssd, and so on).

After creating the services in the ``cinder.conf`` configuration file, you
need to configure one cinder ``volume_type`` per service. Each ``volume_type``
must have the metadata service_label with the same name configured in the
``hnas_svcX_pool_name option`` of that service. See the
:ref:`configuration_example` section for more details. If the ``volume_type``
is not set, the cinder service pool with largest available free space or
other criteria configured in scheduler filters.

.. code-block:: console

   $ openstack volume type create default
   $ openstack volume type set --property service_label=default default
   $ openstack volume type create platinum-tier
   $ openstack volume type set --property service_label=platinum platinum

Multi-backend configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can deploy multiple OpenStack HNAS Driver instances (back ends) that each
controls a separate HNAS or a single HNAS. If you use multiple cinder
back ends, remember that each cinder back end can host up to 4 services. Each
back-end section must have the appropriate configurations to communicate with
your HNAS back end, such as the IP address of the HNAS EVS that is hosting
your data, HNAS SSH access credentials, the configuration of each of the
services in that back end, and so on. You can find examples of such
configurations in the :ref:`configuration_example` section.

If you want the volumes from a volume_type to be casted into a specific
back end, you must configure an extra_spec in the ``volume_type`` with the
value of the ``volume_backend_name`` option from that back end.

For multiple NFS back ends configuration, each back end should have a
separated ``nfs_shares_config`` and also a separated ``nfs_shares file``
defined (For example, ``nfs_shares1``, ``nfs_shares2``) with the desired
shares listed in separated lines.

SSH configuration
~~~~~~~~~~~~~~~~~

.. note::
  As of the Newton OpenStack release, the user can no longer run the
  driver using a locally installed instance of the :command:`SSC` utility
  package. Instead, all communications with the HNAS back end are handled
  through :command:`SSH`.

You can use your username and password to authenticate the Block Storage node
to the HNAS back end. In order to do that, simply configure ``hnas_username``
and ``hnas_password`` in your back end section within the ``cinder.conf``
file.

For example:

.. code-block:: ini

  [hnas-backend]
  # ...
  hnas_username = supervisor
  hnas_password = supervisor

Alternatively, the HNAS cinder driver also supports SSH authentication
through public key. To configure that:

#. If you do not have a pair of public keys already generated, create it in
   the Block Storage node (leave the pass-phrase empty):

   .. code-block:: console

     $ mkdir -p /opt/hitachi/ssh
     $ ssh-keygen -f /opt/hds/ssh/hnaskey

#. Change the owner of the key to cinder (or the user the volume service will
   be run as):

   .. code-block:: console

     # chown -R cinder.cinder /opt/hitachi/ssh

#. Create the directory ``ssh_keys`` in the SMU server:

   .. code-block:: console

     $ ssh [manager|supervisor]@<smu-ip> 'mkdir -p /var/opt/mercury-main/home/[manager|supervisor]/ssh_keys/'

#. Copy the public key to the ``ssh_keys`` directory:

   .. code-block:: console

     $ scp /opt/hitachi/ssh/hnaskey.pub [manager|supervisor]@<smu-ip>:/var/opt/mercury-main/home/[manager|supervisor]/ssh_keys/

#. Access the SMU server:

   .. code-block:: console

     $ ssh [manager|supervisor]@<smu-ip>

#. Run the command to register the SSH keys:

   .. code-block:: console

     $ ssh-register-public-key -u [manager|supervisor] -f ssh_keys/hnaskey.pub

#. Check the communication with HNAS in the Block Storage node:

   For multi-farm HNAS:

   .. code-block:: console

     $ ssh -i /opt/hitachi/ssh/hnaskey [manager|supervisor]@<smu-ip> 'ssc <cluster_admin_ip0> df -a'

   Or, for Single-node/Multi-Cluster:

   .. code-block:: console

     $ ssh -i /opt/hitachi/ssh/hnaskey [manager|supervisor]@<smu-ip> 'ssc localhost df -a'

#. Configure your backend section in ``cinder.conf`` to use your public key:

   .. code-block:: ini

    [hnas-backend]
    # ...
    hnas_ssh_private_key = /opt/hitachi/ssh/hnaskey

Managing volumes
~~~~~~~~~~~~~~~~

If there are some existing volumes on HNAS that you want to import to cinder,
it is possible to use the manage volume feature to do this. The manage action
on an existing volume is very similar to a volume creation. It creates a
volume entry on cinder database, but instead of creating a new volume in the
back end, it only adds a link to an existing volume.

.. note::
  It is an admin only feature and you have to be logged as an user
  with admin rights to be able to use this.

#. Under the :menuselection:`System > Volumes` tab,
   choose the option :guilabel:`Manage Volume`.

#. Fill the fields :guilabel:`Identifier`, :guilabel:`Host`,
   :guilabel:`Volume Name`, and :guilabel:`Volume Type` with volume
   information to be managed:

   * :guilabel:`Identifier`: ip:/type/volume_name (*For example:*
     172.24.44.34:/silver/volume-test)
   * :guilabel:`Host`: `host@backend-name#pool_name` (*For example:*
     `ubuntu@hnas-nfs#test_silver`)
   * :guilabel:`Volume Name`: volume_name (*For example:* volume-test)
   * :guilabel:`Volume Type`: choose a type of volume (*For example:* silver)

By CLI:

.. code-block:: console

  $ cinder manage [--id-type <id-type>][--name <name>][--description <description>]
  [--volume-type <volume-type>][--availability-zone <availability-zone>]
  [--metadata [<key=value> [<key=value> ...]]][--bootable] <host> <identifier>

Example:

.. code-block:: console

  $ cinder manage --name volume-test --volume-type silver
  ubuntu@hnas-nfs#test_silver 172.24.44.34:/silver/volume-test

Managing snapshots
~~~~~~~~~~~~~~~~~~

The manage snapshots feature works very similarly to the manage volumes
feature, currently supported on HNAS cinder drivers. So, if you have a volume
already managed by cinder which has snapshots that are not managed by cinder,
it is possible to use manage snapshots to import these snapshots and link them
with their original volume.

.. note::
  For HNAS NFS cinder driver, the snapshots of volumes are clones of volumes
  that were created using :command:`file-clone-create`, not the HNAS
  :command:`snapshot-\*` feature. Check the HNAS users
  documentation to have details about those 2 features.

Currently, the manage snapshots function does not support importing snapshots
(generally created by storage's :command:`file-clone` operation)
``without parent volumes`` or when the parent volume is ``in-use``. In this
case, the ``manage volumes`` should be used to import the snapshot as a normal
cinder volume.

Also, it is an admin only feature and you have to be logged as a user with
admin rights to be able to use this.

.. note::
  Although there is a verification to prevent importing snapshots using
  non-related volumes as parents, it is possible to manage a snapshot using
  any related cloned volume. So, when managing a snapshot, it is extremely
  important to make sure that you are using the correct parent volume.

.. code-block:: console

  $ cinder snapshot-manage <volume> <identifier>

* :guilabel:`Identifier`: evs_ip:/export_name/snapshot_name
  (*For example:* 172.24.44.34:/export1/snapshot-test)

* :guilabel:`Volume`:  Parent volume ID (*For example:*
  061028c0-60cf-499f-99e2-2cd6afea081f)

Example:

.. code-block:: console

  $ cinder snapshot-manage 061028c0-60cf-499f-99e2-2cd6afea081f 172.24.44.34:/export1/snapshot-test

.. note::
  This feature is currently available only for HNAS NFS Driver.

.. _configuration_example:

Configuration example
~~~~~~~~~~~~~~~~~~~~~

Below are configuration examples for NFS backend:

#. HNAS NFS Driver

   #. For HNAS NFS driver, create this section in your ``cinder.conf`` file:

      .. code-block:: ini

        [hnas-nfs]
        volume_driver = cinder.volume.drivers.hitachi.hnas_nfs.HNASNFSDriver
        nfs_shares_config = /home/cinder/nfs_shares
        volume_backend_name = hnas_nfs_backend
        hnas_username = supervisor
        hnas_password = supervisor
        hnas_mgmt_ip0 = 172.24.44.15

        hnas_svc0_pool_name = nfs_gold
        hnas_svc0_hdp = 172.24.49.21:/gold_export

        hnas_svc1_pool_name = nfs_platinum
        hnas_svc1_hdp = 172.24.49.21:/silver_platinum

        hnas_svc2_pool_name = nfs_silver
        hnas_svc2_hdp = 172.24.49.22:/silver_export

        hnas_svc3_pool_name = nfs_bronze
        hnas_svc3_hdp = 172.24.49.23:/bronze_export

   #. Add it to the ``enabled_backends`` list, under the ``DEFAULT`` section
      of your ``cinder.conf`` file:

      .. code-block:: ini

        [DEFAULT]
        enabled_backends = hnas-nfs

   #. Add the configured exports to the ``nfs_shares`` file:

      .. code-block:: vim

        172.24.49.21:/gold_export
        172.24.49.21:/silver_platinum
        172.24.49.22:/silver_export
        172.24.49.23:/bronze_export

   #. Register a volume type with cinder and associate it with
      this backend:

      .. code-block:: console

         $ openstack volume type create hnas_nfs_gold
         $ openstack volume type set --property volume_backend_name=hnas_nfs_backend \
           service_label=nfs_gold hnas_nfs_gold
         $ openstack volume type create hnas_nfs_platinum
         $ openstack volume type set --property volume_backend_name=hnas_nfs_backend \
           service_label=nfs_platinum hnas_nfs_platinum
         $ openstack volume type create hnas_nfs_silver
         $ openstack volume type set --property volume_backend_name=hnas_nfs_backend \
           service_label=nfs_silver hnas_nfs_silver
         $ openstack volume type create hnas_nfs_bronze
         $ openstack volume type set --property volume_backend_name=hnas_nfs_backend \
           service_label=nfs_bronze hnas_nfs_bronze

Additional notes and limitations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* The ``get_volume_stats()`` function always provides the available
  capacity based on the combined sum of all the HDPs that are used in
  these services labels.

* After changing the configuration on the storage node, the Block Storage
  driver must be restarted.

* On Red Hat, if the system is configured to use SELinux, you need to
  set ``virt_use_nfs = on`` for NFS driver work properly.

  .. code-block:: console

    # setsebool -P virt_use_nfs on

* It is not possible to manage a volume if there is a slash (``/``) or
  a colon (``:``) in the volume name.

* File system ``auto-expansion``: Although supported, we do not recommend using
  file systems with auto-expansion setting enabled because the scheduler uses
  the file system capacity reported by the driver to determine if new volumes
  can be created. For instance, in a setup with a file system that can expand
  to 200GB but is at 100GB capacity, with 10GB free, the scheduler will not
  allow a 15GB volume to be created. In this case, manual expansion would
  have to be triggered by an administrator. We recommend always creating the
  file system at the ``maximum capacity`` or periodically expanding the file
  system manually.

* The ``hnas_svcX_pool_name`` option must be unique for a given back end. It
  is still possible to use the deprecated form ``hnas_svcX_volume_type``, but
  this support will be removed in a future release.

* SSC simultaneous connections limit: In very busy environments, if 2 or
  more volume hosts are configured to use the same storage, some requests
  (create, delete and so on) can have some attempts failed and re-tried (
  ``5 attempts`` by default) due to an HNAS connection limitation (
  ``max of 5`` simultaneous connections).
