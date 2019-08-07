===========================
NEC Storage M series driver
===========================

NEC Storage M series are dual-controller disk arrays which support
online maintenance.
This driver supports both iSCSI and Fibre Channel.

System requirements
~~~~~~~~~~~~~~~~~~~
Supported models:

+-----------------+------------------------+-----------------+
| Storage model   | Storage control        | Disk type       |
|                 | software (firmware)    |                 |
+=================+========================+=================+
| M110,           | 0979 or later          | SSD/HDD hybrid  |
| M310,           |                        |                 |
| M510,           |                        |                 |
| M710            |                        |                 |
+-----------------+------------------------+-----------------+
| M310F,          | 0979 or later          | all flash       |
| M710F           |                        |                 |
+-----------------+------------------------+-----------------+
| M120,           | 1028 or later          | SSD/HDD hybrid  |
| M320            |                        |                 |
+-----------------+------------------------+-----------------+
| M320F           | 1028 or later          | all flash       |
+-----------------+------------------------+-----------------+

Requirements:

- NEC Storage M series requires firmware revision 1028 or later
  to create more than 1024 volumes in a pool.
- NEC Storage DynamicDataReplication license.
- (Optional) NEC Storage IO Load Manager license for QoS.


Supported operations
~~~~~~~~~~~~~~~~~~~~


- Create, delete, attach, and detach volumes.
- Create, list, and delete volume snapshots.
- Create a volume from a snapshot.
- Copy an image to a volume.
- Copy a volume to an image.
- Clone a volume.
- Extend a volume.
- Migrate a volume.
- Get volume statistics.
- Efficient non-disruptive volume backup.
- Manage and unmanage a volume.
- Manage and unmanage a snapshot.
- Attach a volume to multiple instances at once (multi-attach).
- Revert a volume to a snapshot.


Preparation
~~~~~~~~~~~

Below is minimum preparation to a disk array.
For details of each command, see the NEC Storage Manager Command Reference
(IS052).

- Common (iSCSI and Fibre Channel)

  #. Initial setup

     * Set IP addresses for management and BMC with the network configuration
       tool.
     * Enter license keys. (iSMcfg licenserelease)
  #. Create pools

     * Create pools for volumes. (iSMcfg poolbind)
     * Create pools for snapshots. (iSMcfg poolbind)
  #. Create system volumes

     * Create a Replication Reserved Volume (RSV) in one of pools.
       (iSMcfg ldbind)
     * Create Snapshot Reserve Areas (SRAs) in each snapshot pool.
       (iSMcfg srabind)
  #. (Optional) Register SSH public key


- iSCSI only

  #. Set IP addresses of each iSCSI port. (iSMcfg setiscsiport)
  #. Create LD Sets for each node.
     (iSMcfg addldset)
  #. Register initiator names of each node to the corresponding LD Set.
     (iSMcfg addldsetinitiator)


- Fibre Channel only

  #. Start access control. (iSMcfg startacc)
  #. Create LD Sets for each node. (iSMcfg addldset)
  #. Register WWPNs of each node to the corresponding LD Set.
     (iSMcfg addldsetpath)


Configuration
~~~~~~~~~~~~~


Set the following in your ``cinder.conf``, and use the following options
to configure it.

If you use Fibre Channel:

.. code-block:: ini

   [Storage1]
   volume_driver = cinder.volume.drivers.nec.volume.MStorageFCDriver

.. end


If you use iSCSI:

.. code-block:: ini

   [Storage1]
   volume_driver = cinder.volume.drivers.nec.volume.MStorageISCSIDriver

.. end

Also, set ``volume_backend_name``.

.. code-block:: ini

   [DEFAULT]
   volume_backend_name = Storage1

.. end


This table shows configuration options for NEC Storage M series driver.

.. config-table::
   :config-target: NEC Storage M Series

   cinder.volume.drivers.nec.volume_common

Required options
----------------


- ``nec_ismcli_fip``
    FIP address of M-Series Storage.

- ``nec_ismcli_user``
    User name for M-Series Storage iSMCLI.

- ``nec_ismcli_password``
    Password for M-Series Storage iSMCLI.

- ``nec_ismcli_privkey``
    RSA secret key file name for iSMCLI (for public key authentication only).
    Encrypted RSA secret key file cannot be specified.

- ``nec_diskarray_name``
    Diskarray name of M-Series Storage.
    This parameter must be specified to configure multiple groups
    (multi back end) by using the same storage device (storage
    device that has the same ``nec_ismcli_fip``). Specify the disk
    array name targeted by the relevant config-group for this
    parameter.

- ``nec_backup_pools``
    Specify one pool number where snapshots are created. Multiple pools
    are not supported.


Timeout configuration
---------------------


- ``rpc_response_timeout``
    Set the timeout value in seconds. If three or more volumes can be created
    at the same time, the reference value is 30 seconds multiplied by the
    number of volumes created at the same time.
    Also, Specify nova parameters below in ``nova.conf`` file.

    .. code-block:: ini

       [DEFAULT]
       block_device_allocate_retries = 120
       block_device_allocate_retries_interval = 10

    .. end


- ``timeout server (HAProxy configuration)``
    In addition, you need to edit the following value in the HAProxy
    configuration file (``/etc/haproxy/haproxy.cfg``) in an environment where
    HAProxy is used.

    .. code-block:: ini

       timeout server = 600 #Specify a value greater than rpc_response_timeout.

    .. end

    Run the :command:`service haproxy reload` command after editing the
    value to reload the HAProxy settings.

    .. note::

       The OpenStack environment set up using Red Hat OpenStack Platform
       Director may be set to use HAProxy.


Configuration example for /etc/cinder/cinder.conf
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When using one config-group
---------------------------

- When using ``nec_ismcli_password`` to authenticate iSMCLI
  (Password authentication):

  .. code-block:: ini

     [DEFAULT]
     enabled_backends = Storage1

     [Storage1]
     volume_driver = cinder.volume.drivers.nec.volume.MStorageISCSIDriver
     volume_backend_name = Storage1
     nec_ismcli_fip = 192.168.1.10
     nec_ismcli_user = sysadmin
     nec_ismcli_password = sys123
     nec_pools = 0
     nec_backup_pools = 1

  .. end


- When using ``nec_ismcli_privkey`` to authenticate iSMCLI
  (Public key authentication):

  .. code-block:: ini

     [DEFAULT]
     enabled_backends = Storage1

     [Storage1]
     volume_driver = cinder.volume.drivers.nec.volume.MStorageISCSIDriver
     volume_backend_name = Storage1
     nec_ismcli_fip = 192.168.1.10
     nec_ismcli_user = sysadmin
     nec_ismcli_privkey = /etc/cinder/id_rsa
     nec_pools = 0
     nec_backup_pools = 1

  .. end


When using multi config-group (multi-backend)
---------------------------------------------

- Four config-groups (backends)

  Storage1, Storage2, Storage3, Storage4

- Two disk arrays

  200000255C3A21CC(192.168.1.10)
   Example for using config-group, Storage1 and Storage2

  2000000991000316(192.168.1.20)
   Example for using config-group, Storage3 and Storage4

  .. code-block:: ini

     [DEFAULT]
     enabled_backends = Storage1,Storage2,Storage3,Storage4

     [Storage1]
     volume_driver = cinder.volume.drivers.nec.volume.MStorageISCSIDriver
     volume_backend_name = Gold
     nec_ismcli_fip = 192.168.1.10
     nec_ismcli_user = sysadmin
     nec_ismcli_password = sys123
     nec_pools = 0
     nec_backup_pools = 2
     nec_diskarray_name = 200000255C3A21CC

     [Storage2]
     volume_driver = cinder.volume.drivers.nec.volume.MStorageISCSIDriver
     volume_backend_name = Silver
     nec_ismcli_fip = 192.168.1.10
     nec_ismcli_user = sysadmin
     nec_ismcli_password = sys123
     nec_pools = 1
     nec_backup_pools = 3
     nec_diskarray_name = 200000255C3A21CC

     [Storage3]
     volume_driver = cinder.volume.drivers.nec.volume.MStorageISCSIDriver
     volume_backend_name = Gold
     nec_ismcli_fip = 192.168.1.20
     nec_ismcli_user = sysadmin
     nec_ismcli_password = sys123
     nec_pools = 0
     nec_backup_pools = 2
     nec_diskarray_name = 2000000991000316

     [Storage4]
     volume_driver = cinder.volume.drivers.nec.volume.MStorageISCSIDriver
     volume_backend_name = Silver
     nec_ismcli_fip = 192.168.1.20
     nec_ismcli_user = sysadmin
     nec_ismcli_password = sys123
     nec_pools = 1
     nec_backup_pools = 3
     nec_diskarray_name = 2000000991000316

  .. end
