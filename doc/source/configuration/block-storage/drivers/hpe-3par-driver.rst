========================================
HPE 3PAR Driver for OpenStack Cinder
========================================

The ``HPE3PARFCDriver`` and ``HPE3PARISCSIDriver`` drivers, which are based on
the Block Storage service (Cinder) plug-in architecture, run volume operations
by communicating with the HPE 3PAR storage system over HTTP, HTTPS, and SSH
connections. The HTTP and HTTPS communications use ``python-3parclient``,
which is part of the Python standard library.

For information on HPE 3PAR Driver for OpenStack Cinder, refer to
`content kit page <https://www.hpe.com/us/en/product-catalog/storage/storage-software/pip.openstack-device-management-software.1008537377.html>`_.

System requirements
~~~~~~~~~~~~~~~~~~~

To use the HPE 3PAR drivers, install the following software and components on
the HPE 3PAR storage system:

* HPE 3PAR Operating System software version 3.1.3 MU1 or higher.

  * Deduplication provisioning requires SSD disks and HPE 3PAR Operating
    System software version 3.2.1 MU1 or higher.

  * Enabling Flash Cache Policy requires the following:

    * Array must contain SSD disks.

    * HPE 3PAR Operating System software version 3.2.1 MU2 or higher.

    * python-3parclient version 4.2.0 or newer.

    * Flash Cache must be enabled on the array with the CLI command
      :command:`createflashcache SIZE`, where size must be in 16 GB increments.
      For example, :command:`createflashcache 128g` will create 128 GB of Flash
      Cache for each node pair in the array.

  * The Dynamic Optimization is required to support any feature that
    results in a volume changing provisioning type or CPG. This may apply to
    the volume :command:`migrate`, :command:`retype` and :command:`manage`
    commands.

  * The Virtual Copy feature supports any operation that involves
    volume snapshots. This applies to the volume :command:`snapshot-*`
    commands.

  * Enabling Volume Compression requires the following:

    * Array must contain SSD disks.

    * HPE 3PAR Operating System software version 3.3.1 MU1 or higher.

    * HPE 3PAR Storage System with 8k or 20k series

* HPE 3PAR Web Services API Server must be enabled and running.

* One Common Provisioning Group (CPG).

* Additionally, you must install the ``python-3parclient`` version 4.2.0 or
  newer from the Python standard library on the system with the enabled Block
  Storage service volume drivers.

Supported operations
~~~~~~~~~~~~~~~~~~~~

* Create, delete, attach, and detach volumes.

* Create, list, and delete volume snapshots.

* Create a volume from a snapshot.

* Copy an image to a volume.

* Copy a volume to an image.

* Clone a volume.

* Extend a volume.

* Migrate a volume with back-end assistance.

* Retype a volume.

* Manage and unmanage a volume.

* Manage and unmanage a snapshot.

* Replicate host volumes.

* Fail-over host volumes.

* Fail-back host volumes.

* Retype a replicated volume.

* Create, delete, update, snapshot, and clone generic volume groups.

* Create and delete generic volume group snapshots.

* Create a generic volume group from a group snapshot or another group.

* Volume Compression.

* Group Replication with More Granularity (Tiramisu).

* Volume Revert to Snapshot.

* Additional Backend Capabilities.

* Report Backend State in Service List.

* Attach a volume to multiple servers simultaneously (multiattach).

* Peer Persistence.

Volume type support for both HPE 3PAR drivers includes the ability to set the
following capabilities in the OpenStack Block Storage API
``cinder.api.contrib.types_extra_specs`` volume type extra specs extension
module:

* ``hpe3par:snap_cpg``

* ``hpe3par:provisioning``

* ``hpe3par:persona``

* ``hpe3par:vvs``

* ``hpe3par:flash_cache``

* ``hpe3par:compression``

To work with the default filter scheduler, the key values are case sensitive
and scoped with ``hpe3par:``. For information about how to set the key-value
pairs and associate them with a volume type, run the following command:

.. code-block:: console

   $ openstack help volume type

.. note::

   Volumes that are cloned only support the extra specs keys cpg, snap_cpg,
   provisioning and vvs. The others are ignored. In addition the comments
   section of the cloned volume in the HPE 3PAR StoreServ storage array is
   not populated.

If volume types are not used or a particular key is not set for a volume type,
the following defaults are used:

* ``hpe3par:cpg`` - Defaults to the ``hpe3par_cpg`` setting in the
  ``cinder.conf`` file.

* ``hpe3par:snap_cpg`` - Defaults to the ``hpe3par_snap`` setting in
  the ``cinder.conf`` file. If ``hpe3par_snap`` is not set, it defaults
  to the ``hpe3par_cpg`` setting.

* ``hpe3par:provisioning`` - Defaults to ``thin`` provisioning, the valid
  values are ``thin``, ``full``, and ``dedup``.

* ``hpe3par:persona`` - Defaults to the ``2 - Generic-ALUA`` persona. The
  valid values are:

  * ``1 - Generic``
  * ``2 - Generic-ALUA``
  * ``3 - Generic-legacy``
  * ``4 - HPUX-legacy``
  * ``5 - AIX-legacy``
  * ``6 - EGENERA``
  * ``7 - ONTAP-legacy``
  * ``8 - VMware``
  * ``9 - OpenVMS``
  * ``10 - HPUX``
  * ``11 - WindowsServer``

* ``hpe3par:flash_cache`` - Defaults to ``false``, the valid values are
  ``true`` and ``false``.

QoS support for both HPE 3PAR drivers includes the ability to set the
following capabilities in the OpenStack Block Storage API
``cinder.api.contrib.qos_specs_manage`` qos specs extension module:

* ``minBWS``

* ``maxBWS``

* ``minIOPS``

* ``maxIOPS``

* ``latency``

* ``priority``

The qos keys above no longer require to be scoped but must be created and
associated to a volume type. For information about how to set the key-value
pairs and associate them with a volume type, run the following commands:

.. code-block:: console

   $ openstack help volume qos

The following keys require that the HPE 3PAR StoreServ storage array has a
Priority Optimization enabled.

``hpe3par:vvs``
 The virtual volume set name that has been predefined by the Administrator
 with quality of service (QoS) rules associated to it. If you specify
 extra_specs ``hpe3par:vvs``, the qos_specs ``minIOPS``, ``maxIOPS``,
 ``minBWS``, and ``maxBWS`` settings are ignored.

``minBWS``
 The QoS I/O issue bandwidth minimum goal in MBs. If not set, the I/O issue
 bandwidth rate has no minimum goal.

``maxBWS``
 The QoS I/O issue bandwidth rate limit in MBs. If not set, the I/O issue
 bandwidth rate has no limit.

``minIOPS``
 The QoS I/O issue count minimum goal. If not set, the I/O issue count has no
 minimum goal.

``maxIOPS``
 The QoS I/O issue count rate limit. If not set, the I/O issue count rate has
 no limit.

``latency``
 The latency goal in milliseconds.

``priority``
 The priority of the QoS rule over other rules. If not set, the priority is
 ``normal``, valid values are ``low``, ``normal`` and ``high``.

.. note::

   Since the Icehouse release, minIOPS and maxIOPS must be used together to
   set I/O limits. Similarly, minBWS and maxBWS must be used together. If only
   one is set the other will be set to the same value.

The following key requires that the HPE 3PAR StoreServ storage array has an
Adaptive Flash Cache enabled.

* ``hpe3par:flash_cache`` - The flash-cache policy, which can be turned on and
  off by setting the value to ``true`` or ``false``.

* ``hpe3par:compression`` -  The volume compression, which can be turned on and
  off by setting the value to ``true`` or ``false``.

Other restrictions and considerations for ``hpe3par:compression``:

- For a compressed volume, minimum volume size needed is 16 GB; otherwise
  resulting volume will be created successfully but will not be a compressed
  volume.

- A full provisioned volume cannot be compressed,
  if a compression is enabled and provisioning type requested is full,
  the resulting volume defaults to thinly provisioned compressed volume.

LDAP and AD authentication is now supported in the HPE 3PAR driver.

The 3PAR back end must be properly configured for LDAP and AD authentication
prior to configuring the volume driver. For details on setting up LDAP with
3PAR, see the 3PAR user guide.

Once configured, ``hpe3par_username`` and ``hpe3par_password`` parameters in
``cinder.conf`` can be used with LDAP and AD credentials.

Enable the HPE 3PAR Fibre Channel and iSCSI drivers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``HPE3PARFCDriver`` and ``HPE3PARISCSIDriver`` are installed with the
OpenStack software.

#. Install the ``python-3parclient`` Python package on the OpenStack Block
   Storage system.

   .. code-block:: console

      $ pip install 'python-3parclient>=4.0,<5.0'


#. Verify that the HPE 3PAR Web Services API server is enabled and running on
   the HPE 3PAR storage system.

   a. Log onto the HP 3PAR storage system with administrator access.

      .. code-block:: console

         $ ssh 3paradm@<HP 3PAR IP Address>

   b. View the current state of the Web Services API Server.

      .. code-block:: console

         $ showwsapi
         -Service- -State- -HTTP_State- HTTP_Port -HTTPS_State- HTTPS_Port -Version-
         Enabled   Active Enabled       8008        Enabled       8080       1.1

   c. If the Web Services API Server is disabled, start it.

      .. code-block:: console

         $ startwsapi

#. If the HTTP or HTTPS state is disabled, enable one of them.

   .. code-block:: console

      $ setwsapi -http enable

   or

   .. code-block:: console

      $ setwsapi -https enable

   .. note::

      To stop the Web Services API Server, use the :command:`stopwsapi` command. For
      other options run the :command:`setwsapi -h` command.

#. If you are not using an existing CPG, create a CPG on the HPE 3PAR storage
   system to be used as the default location for creating volumes.

#. Make the following changes in the ``/etc/cinder/cinder.conf`` file.

   .. code-block:: ini

      # 3PAR WS API Server URL
      hpe3par_api_url=https://10.10.0.141:8080/api/v1

      # 3PAR username with the 'edit' role
      hpe3par_username=edit3par

      # 3PAR password for the user specified in hpe3par_username
      hpe3par_password=3parpass

      # 3PAR CPG to use for volume creation
      hpe3par_cpg=OpenStackCPG_RAID5_NL

      # IP address of SAN controller for SSH access to the array
      san_ip=10.10.22.241

      # Username for SAN controller for SSH access to the array
      san_login=3paradm

      # Password for SAN controller for SSH access to the array
      san_password=3parpass

      # FIBRE CHANNEL(uncomment the next line to enable the FC driver)
      # volume_driver=cinder.volume.drivers.hpe.hpe_3par_fc.HPE3PARFCDriver

      # iSCSI (uncomment the next line to enable the iSCSI driver and
      # hpe3par_iscsi_ips or iscsi_ip_address)
      #volume_driver=cinder.volume.drivers.hpe.hpe_3par_iscsi.HPE3PARISCSIDriver

      # iSCSI multiple port configuration
      # hpe3par_iscsi_ips=10.10.220.253:3261,10.10.222.234

      # Still available for single port iSCSI configuration
      #iscsi_ip_address=10.10.220.253


      # Enable HTTP debugging to 3PAR
      hpe3par_debug=False

      # Enable CHAP authentication for iSCSI connections.
      hpe3par_iscsi_chap_enabled=false

      # The CPG to use for Snapshots for volumes. If empty hpe3par_cpg will be
      # used.
      hpe3par_cpg_snap=OpenStackSNAP_CPG

      # Time in hours to retain a snapshot. You can't delete it before this
      # expires.
      hpe3par_snapshot_retention=48

      # Time in hours when a snapshot expires and is deleted. This must be
      # larger than retention.
      hpe3par_snapshot_expiration=72

      # The ratio of oversubscription when thin provisioned volumes are
      # involved. Default ratio is 20.0, this means that a provisioned
      # capacity can be 20 times of the total physical capacity.
      max_over_subscription_ratio=20.0

      # This flag represents the percentage of reserved back-end capacity.
      reserved_percentage=15

   .. note::

      You can enable only one driver on each cinder instance unless you enable
      multiple back-end support. See the Cinder multiple back-end support
      instructions to enable this feature.

   .. note::

      You can configure one or more iSCSI addresses by using the
      ``hpe3par_iscsi_ips`` option. Separate multiple IP addresses with a
      comma (``,``). When you configure multiple addresses, the driver selects
      the iSCSI port with the fewest active volumes at attach time. The 3PAR
      array does not allow the default port 3260 to be changed, so IP ports
      need not be specified.

#. Save the changes to the ``cinder.conf`` file and restart the cinder-volume
   service.

The HPE 3PAR Fibre Channel and iSCSI drivers are now enabled on your
OpenStack system. If you experience problems, review the Block Storage
service log files for errors.

The following table contains all the configuration options supported by
the HPE 3PAR Fibre Channel and iSCSI drivers.

.. config-table::
   :config-target: 3PAR

   cinder.volume.drivers.hpe.hpe_3par_common


Specify NSP for FC Bootable Volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Given a system connected to HPE 3PAR via FC and multipath setting is
NOT used in cinder.conf. When the user tries to create a bootable
volume, it fails intermittently with the following error:
Fibre Channel volume device not found

This happens when a zone is created using second or later target from
3PAR backend. In this case, HPE 3PAR client code picks up first target
to form initiator target map. This can be illustrated with below
example.

Sample output of showport command:

``$ showport -sortcol 6``

.. code-block:: console

   N:S:P      Mode State ----Node_WWN---- -Port_WWN/HW_Addr-  Type Protocol Partner FailoverState
   0:1:1    target ready 2FF70002AC002DB6   20110002AC002DB6  host       FC       -             -
   0:1:2    target ready 2FF70002AC002DB6   20120002AC002DB6  host       FC   1:1:2          none
   1:1:1 initiator ready 2FF70002AC002DB6   21110002AC002DB6  rcfc       FC       -             -
   1:1:2    target ready 2FF70002AC002DB6   21120002AC002DB6  host       FC   0:1:2          none
   2:1:1 initiator ready 2FF70002AC002DB6   22110002AC002DB6  rcfc       FC       -             -
   2:1:2    target ready 2FF70002AC002DB6   22120002AC002DB6  host       FC   3:1:2          none
   3:1:1    target ready 2FF70002AC002DB6   23110002AC002DB6  host       FC       -             -
   3:1:2    target ready 2FF70002AC002DB6   23120002AC002DB6  host       FC   2:1:2          none

Suppose zone is created using targets "2:1:2" and "3:1:2" from above
output. Then initiator target map is created using target "0:1:1" only.
In such a case, the path is not found, and bootable volume creation fails.

To avoid above mentioned failure, the user can specify the target in 3PAR
backend section of cinder.conf as follows:

``hpe3par_target_nsp = 3:1:2``

Using above mentioned nsp, respective wwn information is fetched.
Later initiator target map is created using wwn information and
bootable volume is created successfully.

Note: If above mentioned option (nsp) is not specified in cinder.conf,
then the original flow is executed i.e first target is picked and
bootable volume creation may fail.

Peer Persistence support
~~~~~~~~~~~~~~~~~~~~~~~~

Given 3PAR backend configured with replication setup, currently only
Active/Passive replication is supported by 3PAR in OpenStack. When
failover happens, nova does not support volume force-detach (from
dead primary backend) / re-attach to secondary backend. Storage
engineer's manual intervention is required.

To overcome above scenario, support for Peer Persistence is added.
Given a system with Peer Persistence configured and replicated volume
is created. When this volume is attached to an instance, vlun is
created automatically in secondary backend, in addition to primary
backend. So that when a failover happens, it is seamless.

For Peer Persistence support, perform following steps:
1] enable multipath
2] set replication mode as "sync"
3] configure a quorum witness server

Specify ip address of quorum witness server in ``/etc/cinder/cinder.conf``
[within backend section] as given below:

.. code-block:: console

   [3pariscsirep]
   hpe3par_api_url = http://10.50.3.7:8008/api/v1
   hpe3par_username = <user_name>
   hpe3par_password = <password>
   ...
   <other parameters>
   ...
   replication_device = backend_id:CSIM-EOS12_1611702,
                        replication_mode:sync,
                        quorum_witness_ip:10.50.3.192,
                        hpe3par_api_url:http://10.50.3.22:8008/api/v1,
                        ...
                        <other parameters>
                        ...

