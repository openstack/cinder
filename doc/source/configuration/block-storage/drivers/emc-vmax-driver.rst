==================================
Dell EMC VMAX iSCSI and FC drivers
==================================

The Dell EMC VMAX drivers, ``VMAXISCSIDriver`` and ``VMAXFCDriver``, support
the use of Dell EMC VMAX storage arrays with the Cinder Block Storage project.
They both provide equivalent functions and differ only in support for their
respective host attachment methods.

The drivers perform volume operations by communicating with the back-end VMAX
storage management software. They use the Requests HTTP library to communicate
with a Unisphere for VMAX instance, using a RESTAPI interface in the backend
to perform VMAX storage operations.

.. note::

   KNOWN ISSUE:
   Workload support was dropped in ucode 5978. If a VMAX All Flash array is
   upgraded to 5978 or greater and existing volume types leveraged workload
   e.g. DSS, DSS_REP, OLTP and OLTP_REP, attaching and detaching will no
   longer work and the volume type will be unusable. Refrain from upgrading
   to ucode 5978 or greater on an All Flash until a fix is merged. Please
   contact your Dell EMC VMAX customer support representative if in any
   doubt.

System requirements
~~~~~~~~~~~~~~~~~~~

The Dell EMC VMAX Cinder driver supports the VMAX-3 hybrid series and VMAX
All-Flash arrays.

The array operating system software, Solutions Enabler 8.4.0.7 or later, and
Unisphere for VMAX 8.4.0.15 or later are required to run Dell EMC VMAX Cinder
driver.

You can download Solutions Enabler and Unisphere from the Dell EMC's support
web site (login is required). See the ``Solutions Enabler 8.4.0 Installation
and Configuration Guide`` and ``Unisphere for VMAX 8.4.0 Installation Guide``
at ``support.emc.com``.

Required VMAX software suites for OpenStack
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There are five Dell EMC Software Suites sold with the VMAX Hybrid arrays:

- Base Suite
- Advanced Suite
- Local Replication Suite
- Remote Replication Suite
- Total Productivity Pack

The Dell EMC VMAX Cinder driver requires the Advanced Suite and the Local
Replication Suite or the Total Productivity Pack (it includes the Advanced
Suite and the Local Replication Suite) for the VMAX Hybrid.

Using VMAX Remote Replication functionality will also require the Remote
Replication Suite.

For full functionality including SRDF for the VMAX All Flash, the FX package,
or the F package plus the SRDF ``a la carte`` add on is required.

The storage system also requires a Unisphere for VMAX (SMC) eLicence.

Each are licensed separately. For further details on how to get the
relevant license(s), reference eLicensing Support below.


eLicensing support
~~~~~~~~~~~~~~~~~~

To activate your entitlements and obtain your VMAX license files, visit the
Service Center on `<https://support.emc.com>`_, as directed on your License
Authorization Code (LAC) letter emailed to you.

-  For help with missing or incorrect entitlements after activation
   (that is, expected functionality remains unavailable because it is not
   licensed), contact your EMC account representative or authorized reseller.

-  For help with any errors applying license files through Solutions Enabler,
   contact the Dell EMC Customer Support Center.

-  If you are missing a LAC letter or require further instructions on
   activating your licenses through the Online Support site, contact EMC's
   worldwide Licensing team at ``licensing@emc.com`` or call:

   North America, Latin America, APJK, Australia, New Zealand: SVC4EMC
   (800-782-4362) and follow the voice prompts.

   EMEA: +353 (0) 21 4879862 and follow the voice prompts.


Supported operations
~~~~~~~~~~~~~~~~~~~~

VMAX drivers support these operations:

-  Create, list, delete, attach, and detach volumes
-  Create, list, and delete volume snapshots
-  Copy an image to a volume
-  Copy a volume to an image
-  Clone a volume
-  Extend a volume
-  Retype a volume (Host and storage assisted volume migration)
-  Create a volume from a snapshot
-  Create and delete generic volume group
-  Create and delete generic volume group snapshot
-  Modify generic volume group (add and remove volumes)
-  Create generic volume group from source
-  Live Migration
-  Volume replication SRDF/S, SRDF/A and SRDF Metro
-  Quality of service (QoS)
-  Manage and unmanage volumes and snapshots

VMAX drivers also support the following features:

-  Dynamic masking view creation
-  Dynamic determination of the target iSCSI IP address
-  iSCSI multipath support
-  Oversubscription
-  Service Level support
-  SnapVX support
-  Compression support(All Flash only)
-  CHAP Authentication

.. note::

   VMAX All Flash array with Solutions Enabler 8.3.0.11 or later have
   compression enabled by default when associated with Diamond Service Level.
   This means volumes added to any newly created storage groups will be
   compressed.

.. note::

   Since the release of the PowerMax in May 2018, ``Unisphere for PowerMax
   9.0.0.6`` can support new PowerMax features such as ``Deduplication``
   and ``Online Device Expansion of Replicated volumes``. ``Restore Volume
   From Snapshot`` is also supported on all VMAX All Flash and PowerMax
   arrays.


VMAX Driver Integration
~~~~~~~~~~~~~~~~~~~~~~~

#. Download Solutions Enabler from ``support.emc.com`` and install it.

   You can install Solutions Enabler on a non-OpenStack host. Supported
   platforms include different flavors of Windows, Red Hat, and SUSE Linux.
   Solutions Enabler can be installed on a physical server, or as a Virtual
   Appliance (a VMware ESX server VM). Additionally, starting with HYPERMAX
   OS Q3 2015, you can manage VMAX3 arrays using the Embedded Management
   (eManagement) container application. See the ``Solutions Enabler 8.4.0
   Installation and Configuration Guide`` on ``support.emc.com`` for more
   details.

   .. note::

      You must discover storage arrays before you can use the VMAX drivers.
      Follow instructions in ``Solutions Enabler 8.4.0 Installation and
      Configuration Guide`` on ``support.emc.com`` for more
      details.

#. Download Unisphere from ``support.emc.com`` and install it.

   Unisphere can be installed in local, remote, or embedded configurations
   - i.e., on the same server running Solutions Enabler; on a server
   connected to the Solutions Enabler server; or using the eManagement
   container application (containing Solutions Enabler and Unisphere for
   VMAX). See ``Unisphere for VMAX 8.4.0 Installation Guide`` at
   ``support.emc.com``.

#. Configure Block Storage in cinder.conf

   .. note::

      For security and backend uniformity, the use of the XML file for VMAX
      backend configuration has been deprecated in Queens. While the xml file
      usage will still be supported, a warning will be issued on its impending
      deprecation.

   +-----------------+------------------------+---------+----------+---------------------------+
   |  VMAX parameter | cinder.conf parameter  | Default | Required | Description               |
   +=================+========================+=========+==========+===========================+
   |  RestServerIp   | san_ip                 | "       | Yes      | IP address of the         |
   |                 |                        |         |          | Unisphere server          |
   +-----------------+------------------------+---------+----------+---------------------------+
   |  RestServerPort | san_rest_port          | 8443    | No       | Port of the               |
   |                 |                        |         |          | Unisphere server          |
   +-----------------+------------------------+---------+----------+---------------------------+
   |  RestUserName   | san_login              | 'admin' | Yes      | Username of the           |
   |                 |                        |         |          | Unisphere server          |
   +-----------------+------------------------+---------+----------+---------------------------+
   |  RestPassword   | san_password           | "       | Yes      | Password of the           |
   |                 |                        |         |          | Unisphere server          |
   +-----------------+------------------------+---------+----------+---------------------------+
   |  Array          | vmax_array             | None    | Yes      | Unique VMAX array         |
   |                 |                        |         |          | serial number             |
   +-----------------+------------------------+---------+----------+---------------------------+
   |  SRP            | vmax_srp               | None    | Yes      | Name of the               |
   |                 |                        |         |          | storage resource pool     |
   +-----------------+------------------------+---------+----------+---------------------------+
   |  PortGroups     | vmax_port_groups       | None    | Yes      | The name(s) of VMAX       |
   |                 |                        |         |          | port group(s)             |
   +-----------------+------------------------+---------+----------+---------------------------+
   |  SSLVerify      | driver_ssl_cert_verify | False   | No       | The path to the           |
   |                 | driver_ssl_cert_path   | None    | No       | ``my_unisphere_host.pem`` |
   +-----------------+------------------------+---------+----------+---------------------------+

   .. note::

      ``san_rest_port`` is ``8443`` by default but can be changed if
      necessary. For the purposes of this documentation the default is
      assumed so the tag will not appear in any of the ``cinder.conf``
      extracts below.

   .. note::

      VMAX ``PortGroups`` must be pre-configured to expose volumes managed
      by the array. Port groups can be supplied in the ``cinder.conf``, or
      can be specified as an extra spec ``storagetype:portgroupname`` on a
      volume type. The latter gives the user more control. When a dynamic
      masking view is created by the VMAX driver, if there is no port group
      specified as an extra specification, the port group is chosen randomly
      from the PortGroup list, to evenly distribute load across the set of
      groups provided.

   .. note::

      Service Level and workload can be added to the cinder.conf when the
      backend is the default case and there is no associated volume type.
      This not a recommended configuration as it is too restrictive.

      +-----------------+------------------------+---------+----------+
      |  VMAX parameter | cinder.conf parameter  | Default | Required |
      +=================+========================+=========+==========+
      |  ServiceLevel   | vmax_service_level     | None    | No       |
      +-----------------+------------------------+---------+----------+
      |  Workload       | vmax_workload          | None    | No       |
      +-----------------+------------------------+---------+----------+

   Configure Block Storage in cinder.conf

   Add the following entries to ``/etc/cinder/cinder.conf``:

   .. code-block:: ini

      enabled_backends = CONF_GROUP_ISCSI, CONF_GROUP_FC

      [CONF_GROUP_ISCSI]
      volume_driver = cinder.volume.drivers.dell_emc.vmax.iscsi.VMAXISCSIDriver
      volume_backend_name = VMAX_ISCSI_DIAMOND
      vmax_port_groups = [OS-ISCSI-PG]
      san_ip = 10.10.10.10
      san_login = my_username
      san_password = my_password
      vmax_array = 000123456789
      vmax_srp = SRP_1


      [CONF_GROUP_FC]
      volume_driver = cinder.volume.drivers.dell_emc.vmax.fc.VMAXFCDriver
      volume_backend_name = VMAX_FC_DIAMOND
      vmax_port_groups = [OS-FC-PG]
      san_ip = 10.10.10.10
      san_login = my_username
      san_password = my_password
      vmax_array = 000123456789
      vmax_srp = SRP_1

   In this example, two back-end configuration groups are enabled:
   ``CONF_GROUP_ISCSI`` and ``CONF_GROUP_FC``. Each configuration group has a
   section describing unique parameters for connections, drivers and the
   ``volume_backend_name``.

#. Create Volume Types

   Once the ``cinder.conf`` has been updated,  :command:`openstack` commands
   need to be issued in order to create and associate OpenStack volume types
   with the declared ``volume_backend_names``.

   Additionally, each volume type will need an associated ``pool_name`` - an
   extra specification indicating the service level/ workload combination to
   be used for that volume type.

   There is also the option to assign a port group to a volume type by
   setting the ``storagetype:portgroupname`` extra specification.

   .. note::

      It is possible to create as many volume types as the number of Service Level
      and Workload(available) combination for provisioning volumes. The pool_name
      is the additional property which has to be set and is of the format:
      ``<ServiceLevel>+<Workload>+<SRP>+<Array ID>``.
      This can be obtained from the output of the ``cinder get-pools--detail``.

   .. code-block:: console

      $ openstack volume type create VMAX_ISCSI_SILVER_OLTP
      $ openstack volume type set --property volume_backend_name=ISCSI_backend \
                                  --property pool_name=Silver+OLTP+SRP_1+000123456789 \
                                  --property storagetype:portgroupname=OS-PG2 \
                                  VMAX_ISCSI_SILVER_OLTP
      $ openstack volume type create VMAX_FC_DIAMOND_DSS
      $ openstack volume type set --property volume_backend_name=FC_backend \
                                  --property pool_name=Diamond+DSS+SRP_1+000123456789 \
                                  --property storagetype:portgroupname=OS-PG1 \
                                  VMAX_FC_DIAMOND_DSS


   By issuing these commands, the Block Storage volume type
   ``VMAX_ISCSI_SILVER_OLTP`` is associated with the ``ISCSI_backend``, a Silver
   Service Level, and an OLTP workload.

   The type ``VMAX_FC_DIAMOND_DSS`` is associated with the ``FC_backend``, a
   Diamond Service Level, and a DSS workload.

   The ``ServiceLevel`` manages the underlying storage to provide expected
   performance. Setting the ``ServiceLevel`` to ``None`` means that non-FAST
   managed storage groups will be created instead (storage groups not
   associated with any service level). If ``ServiceLevel`` is ``None`` then
   ``Workload`` must be ``None``.

   .. code-block:: console

      openstack volume type set --property pool_name=None+None+SRP_1+000123456789

   When a ``Workload`` is added, the latency range is reduced due to the
   added information. Setting the ``Workload`` to ``None`` means the latency
   range will be the widest for its Service Level type. Please note that you
   cannot set a Workload without a Service Level.

   .. code-block:: console

      openstack volume type set --property pool_name=Diamond+None+SRP_1+000123456789

   .. note::

      VMAX Hybrid supports Optimized, Diamond, Platinum, Gold, Silver, Bronze,
      and NONE service levels. VMAX All Flash supports Diamond and None. Both
      support DSS_REP, DSS, OLTP_REP, OLTP, and None workloads.


Upgrading from SMI-S based driver to RESTAPI based driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Seamless upgrades from an SMI-S based driver to RESTAPI based driver,
following the setup instructions above, are supported with a few exceptions:

#. Live migration functionality will not work on already attached/in-use
   legacy volumes. These volumes will first need to be detached and reattached
   using the RESTAPI based driver. This is because we have changed the masking
   view architecture from Pike to better support this functionality.

#. Consistency groups are deprecated in Pike. Generic Volume Groups are
   supported from Pike onwards.


SSL support
~~~~~~~~~~~

#. Get the CA certificate of the Unisphere server. This pulls the CA cert file
   and saves it as .pem file:

   .. code-block:: console

      # openssl s_client -showcerts \
                         -connect my_unisphere_host:8443 </dev/null 2>/dev/null \
                         | openssl x509 -outform PEM > my_unisphere_host.pem

   Where ``my_unisphere_host`` is the hostname of the unisphere instance and
   ``my_unisphere_host.pem`` is the name of the .pem file.

#. Add this path to the ``cinder.conf`` under the backend stanza

   .. code-block:: console

      driver_ssl_cert_path = /path/to/my_unisphere_host.pem

   ``OR`` follow the steps below:

#. OPTIONAL (if step 2 completed): Copy the pem file to the system certificate
   directory:

   .. code-block:: console

      # cp my_unisphere_host.pem /usr/share/ca-certificates/ca_cert.crt

#. OPTIONAL: Update CA certificate database with the following commands:

   .. code-block:: console

      # sudo dpkg-reconfigure ca-certificates

   .. note::

      Check that the new ``ca_cert.crt`` will activate by selecting ask on the
      dialog. If it is not enabled for activation, use the down and up keys to
      select, and the space key to enable or disable.

      .. code-block:: console

         # sudo update-ca-certificates

#. Ensure ``driver_ssl_cert_verify`` is set to ``True`` in cinder.conf backend
   stanza ``OR`` the path defined in step 1.


.. note::

   Issue

   "Caused by SSLError(CertificateError("hostname 'xx.xx.xx.xx' doesn't match 'xx.xx.xx.xx'

   Solution

   #. Check that ``requests`` and it's dependencies are up to date:

      .. code-block:: console

         $ sudo pip install requests --upgrade

   #. Verify the SSL cert was created using the command:

      .. code-block:: console

         $ openssl s_client -showcerts -connect {my_unisphere_host}:{port} </dev/null 2>/dev/null|openssl x509 -outform PEM >{cert_name}.pem

   #. Verify the cert using command:

      .. code-block:: console

         $ openssl s_client -connect {ip_address}:{port} -CAfile {cert_name}.pem -verify 9

   #. If requests is up to date and the cert is created correctly and verified
      but the hostname error still persists, install ``ipaddress`` to
      determine if it clears the hostname error:

      .. code-block:: console

         $ sudo pip install ipaddress


FC Zoning with VMAX
~~~~~~~~~~~~~~~~~~~

Zone Manager is required when there is a fabric between the host and array.
This is necessary for larger configurations where pre-zoning would be too
complex and open-zoning would raise security concerns.

iSCSI with VMAX
~~~~~~~~~~~~~~~

-  Make sure the ``iscsi-initiator-utils`` package is installed on all Compute
   nodes.

.. note::

   You can only ping the VMAX iSCSI target ports when there is a valid masking
   view. An attach operation creates this masking view.

VMAX masking view and group naming info
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Masking view names
------------------

Masking views are dynamically created by the VMAX FC and iSCSI drivers using
the following naming conventions. ``[protocol]`` is either ``I`` for volumes
attached over iSCSI or ``F`` for volumes attached over Fiber Channel.

.. code-block:: text

   OS-[shortHostName]-[protocol]-[portgroup_name]-MV

Initiator group names
---------------------

For each host that is attached to VMAX volumes using the drivers, an initiator
group is created or re-used (per attachment type). All initiators of the
appropriate type known for that host are included in the group. At each new
attach volume operation, the VMAX driver retrieves the initiators (either
WWNNs or IQNs) from OpenStack and adds or updates the contents of the
Initiator Group as required. Names are of the following format. ``[protocol]``
is either ``I`` for volumes attached over iSCSI or ``F`` for volumes attached
over Fiber Channel.

.. code-block:: console

   OS-[shortHostName]-[protocol]-IG

.. note::

   Hosts attaching to OpenStack managed VMAX storage cannot also attach to
   storage on the same VMAX that are not managed by OpenStack.

FA port groups
--------------

VMAX array FA ports to be used in a new masking view are retrieved from the
port group provided as the extra spec on the volume type, or chosen from the
list provided in the Dell EMC configuration file.

Storage group names
-------------------

As volumes are attached to a host, they are either added to an existing
storage group (if it exists) or a new storage group is created and the volume
is then added. Storage groups contain volumes created from a pool, attached
to a single host, over a single connection type (iSCSI or FC). ``[protocol]``
is either ``I`` for volumes attached over iSCSI or ``F`` for volumes attached
over Fiber Channel. VMAX cinder driver utilizes cascaded storage groups -
a ``parent`` storage group which is associated with the masking view, which
contains ``child`` storage groups for each configured
SRP/slo/workload/compression-enabled or disabled/replication-enabled or
disabled combination.

VMAX All Flash and Hybrid

Parent storage group:

.. code-block:: text

   OS-[shortHostName]-[protocol]-[portgroup_name]-SG

Child storage groups:

.. code-block:: text

   OS-[shortHostName]-[SRP]-[ServiceLevel/Workload]-[portgroup_name]-CD-RE

.. note::

   CD and RE are only set if compression is explicitly disabled or replication
   explicitly enabled. See the compression and replication sections below.

Interval and Retries
--------------------

By default, ``interval`` and ``retries`` are ``3`` seconds and ``200`` retries
respectively. These determine how long (``interval``) and how many times
(``retries``) a user is willing to wait for a single Rest call,
``3*200=600seconds``. Depending on usage, these may need to be overridden by
the user in the cinder.conf. For example, if performance is a factor, then the
``interval`` should be decreased to check the job status more frequently, and
if multiple concurrent provisioning requests are issued then ``retries``
should be increased so calls will not timeout prematurely.

In the example below, the driver checks every 3 seconds for the status of the
job. It will continue checking for 200 retries before it times out.

Add the following lines to the VMAX backend in the cinder.conf:

.. code-block:: console

   [CONF_GROUP_ISCSI]
   volume_driver = cinder.volume.drivers.dell_emc.vmax.iscsi.VMAXISCSIDriver
   volume_backend_name = VMAX_ISCSI_DIAMOND
   vmax_port_groups = [OS-ISCSI-PG]
   san_ip = 10.10.10.10
   san_login = my_username
   san_password = my_password
   vmax_array = 000123456789
   vmax_srp = SRP_1
   interval = 3
   retries = 200


QoS (Quality of Service) support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Quality of service (QoS) has traditionally been associated with network
bandwidth usage. Network administrators set limitations on certain networks
in terms of bandwidth usage for clients. This enables them to provide a
tiered level of service based on cost. The Nova/cinder QoS offer similar
functionality based on volume type setting limits on host storage bandwidth
per service offering. Each volume type is tied to specific QoS attributes
some of which are unique to each storage vendor. In the hypervisor, the QoS
limits the following:

- Limit by throughput - Total bytes/sec, read bytes/sec, write bytes/sec
- Limit by IOPS - Total IOPS/sec, read IOPS/sec, write IOPS/sec

QoS enforcement in cinder is done either at the hypervisor (front end),
the storage subsystem (back end), or both. This section focuses on QoS
limits that are enforced by either the VMAX backend and the hypervisor
front end interchangeably or just back end (Vendor Specific). The VMAX driver
offers support for Total bytes/sec limit in throughput and Total IOPS/sec
limit of IOPS.

The VMAX driver supports the following attributes that are front end/back end
agnostic

- total_iops_sec - Maximum IOPs (in I/Os per second). Valid values range from
  100 IO/Sec to 100,000 IO/sec.
- total_bytes_sec - Maximum bandwidth (throughput) in bytes per second. Valid
  values range from 1048576 bytes (1MB) to 104857600000 bytes (100, 000MB)

The VMAX driver offers the following attribute that is vendor specific to the
VMAX and dependent on the total_iops_sec and/or total_bytes_sec being set.

- Dynamic Distribution - Enables/Disables dynamic distribution of host I/O
  limits. Possible values are:

  - Always - Enables full dynamic distribution mode. When enabled, the
    configured host I/O limits will be dynamically distributed across the
    configured ports, thereby allowing the limits on each individual port to
    adjust to fluctuating demand.
  - OnFailure - Enables port failure capability. When enabled, the fraction
    of configured host I/O limits available to a configured port will adjust
    based on the number of ports currently online.
  - Never - Disables this feature (Default).

USE CASE 1 - Default values
---------------------------

Prerequisites - VMAX

- Host I/O Limit (MB/Sec) -     No Limit
- Host I/O Limit (IO/Sec) -     No Limit
- Set Dynamic Distribution -    N/A

.. table:: **Prerequisites - Block Storage (cinder) back end (storage group)**

 +-------------------+-------------------+
 |  Key              | Value             |
 +===================+===================+
 |  total_iops_sec   |  500              |
 +-------------------+-------------------+
 |  total_bytes_sec  | 104857600 (100MB) |
 +-------------------+-------------------+
 |  DistributionType | Always            |
 +-------------------+-------------------+

#. Create QoS Specs with the prerequisite values above:

   .. code-block:: console

      $ openstack volume qos create --consumer back-end \
                                    --property total_iops_sec=500 \
                                    --property total_bytes_sec=104857600 \
                                    --property DistributionType=Always \
                                    my_qos

#. Associate QoS specs with specified volume type:

   .. code-block:: console

      $ openstack volume qos associate my_qos my_volume_type

#. Create volume with the volume type indicated above:

   .. code-block:: console

      $ openstack volume create --size 1 --type my_volume_type my_volume

**Outcome - VMAX (storage group)**

- Host I/O Limit (MB/Sec) -     100
- Host I/O Limit (IO/Sec) -     500
- Set Dynamic Distribution -    Always

**Outcome - Block Storage (cinder)**

Volume is created against volume type and QoS is enforced with the parameters
above.

USE CASE 2 - Preset limits
--------------------------

Prerequisites - VMAX

- Host I/O Limit (MB/Sec) -     2000
- Host I/O Limit (IO/Sec) -     2000
- Set Dynamic Distribution -    Never

.. table:: **Prerequisites - Block Storage (cinder) back end (storage group)**

 +-------------------+-------------------+
 |  Key              | Value             |
 +===================+===================+
 |  total_iops_sec   | 500               |
 +-------------------+-------------------+
 |  total_bytes_sec  | 104857600 (100MB) |
 +-------------------+-------------------+
 |  DistributionType | Always            |
 +-------------------+-------------------+

#. Create QoS specifications with the prerequisite values above. The consumer
   in this case use case is both for front end and back end:

   .. code-block:: console

      $ openstack volume qos create --consumer back-end \
                                    --property total_iops_sec=500 \
                                    --property total_bytes_sec=104857600 \
                                    --property DistributionType=Always \
                                    my_qos

#. Associate QoS specifications with specified volume type:

   .. code-block:: console

      $ openstack volume qos associate my_qos my_volume_type

#. Create volume with the volume type indicated above:

   .. code-block:: console

      $ openstack volume create --size 1 --type my_volume_type my_volume

#. Attach the volume created in step 3 to an instance

   .. code-block:: console

      $ openstack server add volume my_volume my_instance

**Outcome - VMAX (storage group)**

- Host I/O Limit (MB/Sec) -     100
- Host I/O Limit (IO/Sec) -     500
- Set Dynamic Distribution -    Always

**Outcome - Block Storage (cinder)**

Volume is created against volume type and QoS is enforced with the parameters
above.

**Outcome - Hypervisor (nova)**

Libvirt includes an extra xml flag within the <disk> section called iotune
that is responsible for rate limitation. To confirm that, first get the
``OS-EXT-SRV-ATTR:instance_name`` value of the server instance
i.e. instance-00000003.

.. code-block:: console

   $ openstack server show <serverid>

   +-------------------------------------+-----------------------------------------------------------------+
   | Field                               | Value                                                           |
   +-------------------------------------+-----------------------------------------------------------------+
   | OS-DCF:diskConfig                   | AUTO                                                            |
   | OS-EXT-AZ:availability_zone         | nova                                                            |
   | OS-EXT-SRV-ATTR:host                | myhost                                                          |
   | OS-EXT-SRV-ATTR:hypervisor_hostname | myhost                                                          |
   | OS-EXT-SRV-ATTR:instance_name       | instance-00000003                                               |
   | OS-EXT-STS:power_state              | Running                                                         |
   | OS-EXT-STS:task_state               | None                                                            |
   | OS-EXT-STS:vm_state                 | active                                                          |
   | OS-SRV-USG:launched_at              | 2017-11-02T08:15:42.000000                                      |
   | OS-SRV-USG:terminated_at            | None                                                            |
   | accessIPv4                          |                                                                 |
   | accessIPv6                          |                                                                 |
   | addresses                           | private=fd21:99c2:73f3:0:f816:3eff:febe:30ed, 10.0.0.3          |
   | config_drive                        |                                                                 |
   | created                             | 2017-11-02T08:15:34Z                                            |
   | flavor                              | m1.tiny (1)                                                     |
   | hostId                              | e7b8312581f9fbb8508587d45c0b6fb4dc86102c632ed1f3a6a49d42        |
   | id                                  | 0ef0ff4c-dbda-4dc7-b8ed-45d2fc2f31db                            |
   | image                               | cirros-0.3.5-x86_64-disk (b7c220f5-2408-4296-9e58-fc5a41cb7e9d) |
   | key_name                            | myhostname                                                      |
   | name                                | myhosthame                                                      |
   | progress                            | 0                                                               |
   | project_id                          | bae4b97a0d8b42c28a5add483981e5db                                |
   | properties                          |                                                                 |
   | security_groups                     | name='default'                                                  |
   | status                              | ACTIVE                                                          |
   | updated                             | 2017-11-02T08:15:42Z                                            |
   | user_id                             | 7bccf456740546799a7e20457f13c38b                                |
   | volumes_attached                    |                                                                 |
   +-------------------------------------+-----------------------------------------------------------------+

We then run the following command using the
``OS-EXT-SRV-ATTR:instance_name`` retrieved above.

.. code-block:: console

   $ virsh dumpxml instance-00000003 | grep -1 "total_bytes_sec\|total_iops_sec"

The output of the command contains the xml below. It is found between the
``<disk>`` start and end tag.

.. code-block:: xml

   <iotune>
      <total_bytes_sec>104857600</total_bytes_sec>
      <total_iops_sec>500</total_iops_sec>
   </iotune>


USE CASE 3 - Preset limits
--------------------------

Prerequisites - VMAX

- Host I/O Limit (MB/Sec) -     100
- Host I/O Limit (IO/Sec) -     500
- Set Dynamic Distribution -    Always

.. table:: **Prerequisites - Block Storage (cinder) back end (storage group)**

 +-------------------+-------------------+
 |  Key              | Value             |
 +===================+===================+
 |  total_iops_sec   | 500               |
 +-------------------+-------------------+
 |  total_bytes_sec  | 104857600 (100MB) |
 +-------------------+-------------------+
 |  DistributionType | OnFailure         |
 +-------------------+-------------------+

#. Create QoS specifications with the prerequisite values above:

   .. code-block:: console

      $ openstack volume qos create --consumer back-end \
                                    --property total_iops_sec=500 \
                                    --property total_bytes_sec=104857600 \
                                    --property DistributionType=Always \
                                    my_qos

#. Associate QoS specifications with specified volume type:

   .. code-block:: console

      $ openstack volume qos associate my_qos my_volume

#. Create volume with the volume type indicated above:

   .. code-block:: console

      $ openstack volume create --size 1 --type my_volume_type my_volume

**Outcome - VMAX (storage group)**

- Host I/O Limit (MB/Sec) -     100
- Host I/O Limit (IO/Sec) -     500
- Set Dynamic Distribution -    OnFailure

**Outcome - Block Storage (cinder)**

Volume is created against volume type and QOS is enforced with the parameters above


USE CASE 4 - Default values
---------------------------

Prerequisites - VMAX

- Host I/O Limit (MB/Sec) -     No Limit
- Host I/O Limit (IO/Sec) -     No Limit
- Set Dynamic Distribution -    N/A

.. table:: **Prerequisites - Block Storage (cinder) back end (storage group)**

 +-------------------+-----------+
 |  Key              | Value     |
 +===================+===========+
 |  DistributionType | Always    |
 +-------------------+-----------+

#. Create QoS specifications with the prerequisite values above:

   .. code-block:: console

      $ openstack volume qos create --consumer back-end \
                                    --property DistributionType=Always \
                                    my_qos

#. Associate QoS specifications with specified volume type:

   .. code-block:: console

      $ openstack volume qos associate my_qos my_volume_type


#. Create volume with the volume type indicated above:

   .. code-block:: console

      $ openstack volume create --size 1 --type my_volume_type my_volume

**Outcome - VMAX (storage group)**

- Host I/O Limit (MB/Sec) -     No Limit
- Host I/O Limit (IO/Sec) -     No Limit
- Set Dynamic Distribution -    N/A

**Outcome - Block Storage (cinder)**

Volume is created against volume type and there is no QoS change.

iSCSI multipathing support
~~~~~~~~~~~~~~~~~~~~~~~~~~

- Install open-iscsi on all nodes on your system
- Do not install EMC PowerPath as they cannot co-exist with native multipath
  software
- Multipath tools must be installed on all nova compute nodes

On Ubuntu:

.. code-block:: console

   # apt-get install multipath-tools      #multipath modules
   # apt-get install sysfsutils sg3-utils #file system utilities
   # apt-get install scsitools            #SCSI tools

On openSUSE and SUSE Linux Enterprise Server:

.. code-block:: console

   # zipper install multipath-tools      #multipath modules
   # zipper install sysfsutils sg3-utils #file system utilities
   # zipper install scsitools            #SCSI tools

On Red Hat Enterprise Linux and CentOS:

.. code-block:: console

   # yum install iscsi-initiator-utils   #ensure iSCSI is installed
   # yum install device-mapper-multipath #multipath modules
   # yum install sysfsutils sg3-utils    #file system utilities


Multipath configuration file
----------------------------

The multipath configuration file may be edited for better management and
performance. Log in as a privileged user and make the following changes to
:file:`/etc/multipath.conf` on the  Compute (nova) node(s).

.. code-block:: vim

   devices {
   # Device attributed for EMC VMAX
       device {
               vendor "EMC"
               product "SYMMETRIX"
               path_grouping_policy multibus
               getuid_callout "/lib/udev/scsi_id --page=pre-spc3-83 --whitelisted --device=/dev/%n"
               path_selector "round-robin 0"
               path_checker tur
               features "0"
               hardware_handler "0"
               prio const
               rr_weight uniform
               no_path_retry 6
               rr_min_io 1000
               rr_min_io_rq 1
       }
   }

You may need to reboot the host after installing the MPIO tools or restart
iSCSI and multipath services.

On Ubuntu:

.. code-block:: console

   # service open-iscsi restart
   # service multipath-tools restart

On openSUSE, SUSE Linux Enterprise Server, Red Hat Enterprise Linux, and
CentOS:

.. code-block:: console

   # systemctl restart open-iscsi
   # systemctl restart multipath-tools

.. code-block:: console

   $ lsblk
   NAME                                       MAJ:MIN RM   SIZE RO TYPE  MOUNTPOINT
   sda                                          8:0    0     1G  0 disk
   ..360000970000196701868533030303235 (dm-6) 252:6    0     1G  0 mpath
   sdb                                          8:16   0     1G  0 disk
   ..360000970000196701868533030303235 (dm-6) 252:6    0     1G  0 mpath
   vda                                        253:0    0     1T  0 disk

OpenStack configurations
------------------------

On Compute (nova) node, add the following flag in the ``[libvirt]`` section of
:file:`/etc/nova/nova.conf` and :file:`/etc/nova/nova-cpu.conf`:

.. code-block:: ini

   volume_use_multipath = True

On cinder controller node, iSCSI MPIO can be set globally in the
[DEFAULT] section or set individually in the VMAX backend stanza in
:file:`/etc/cinder/cinder.conf`:

.. code-block:: ini

   use_multipath_for_image_xfer = True

Restart ``nova-compute`` and ``cinder-volume`` services after the change.

Verify you have multiple initiators available on the compute node for I/O
-------------------------------------------------------------------------

#. Create a 3GB VMAX volume.
#. Create an instance from image out of native LVM storage or from VMAX
   storage, for example, from a bootable volume
#. Attach the 3GB volume to the new instance:

   .. code-block:: console

      # multipath -ll
      mpath102 (360000970000196700531533030383039) dm-3 EMC,SYMMETRIX
      size=3G features='1 queue_if_no_path' hwhandler='0' wp=rw
      '-+- policy='round-robin 0' prio=1 status=active
      33:0:0:1 sdb 8:16 active ready running
      '- 34:0:0:1 sdc 8:32 active ready running

#. Use the ``lsblk`` command to see the multipath device:

   .. code-block:: console

      # lsblk
      NAME                                       MAJ:MIN RM   SIZE RO TYPE  MOUNTPOINT
      sdb                                          8:0    0     3G  0 disk
      ..360000970000196700531533030383039 (dm-6) 252:6    0     3G  0 mpath
      sdc                                          8:16   0     3G  0 disk
      ..360000970000196700531533030383039 (dm-6) 252:6    0     3G  0 mpath
      vda


CHAP Authentication Support
~~~~~~~~~~~~~~~~~~~~~~~~~~~

This supports one way initiator CHAP authentication functionality into the
VMAX backend. With CHAP one-way authentication, the storage array challenges
the host during the initial link negotiation process and expects to receive
a valid credential and CHAP secret in response. When challenged, the host
transmits a CHAP credential and CHAP secret to the storage array. The storage
array looks for this credential and CHAP secret which stored in the host
initiator's initiator group (IG) information in the ACLX database. Once a
positive authentication occurs, the storage array sends an acceptance message
to the host. However, if the storage array fails to find any record of the
credential/secret pair, it sends a rejection message, and the link is closed.

Assumptions, Restrictions and Pre-Requisites
--------------------------------------------

#. The host initiator IQN is required along with the credentials the host
   initiator will use to log into the storage array with. The same credentials
   should be used in a multi node system if connecting to the same array.

#. Enable one way CHAP authentication for the iscsi initiator on the storage
   array using SYMCLI. Template and example shown below. For the purpose of
   this setup, the credential/secret used would be my_username/my_password
   with iscsi initiator of iqn.1991-05.com.company.lcseb130

   .. code-block:: console

      # symaccess -sid <SymmID> -iscsi <iscsi>
                  enable chap |
                  disable chap |
                  set chap -cred <Credential> -secret <Secret>

      # symaccess -sid 128 \
                  -iscsi iqn.1991-05.com.company.lcseb130 \
                  set chap -cred my_username -secret my_password



Settings and Configuration
--------------------------

#. Set the configuration in the VMAX backend group in cinder.conf using the
   following parameters and restart cinder.

   +-----------------------+-------------------------+-------------------+
   | Configuration options | Value required for CHAP | Required for CHAP |
   +=======================+=========================+===================+
   |  use_chap_auth        | True                    | Yes               |
   +-----------------------+-------------------------+-------------------+
   |  chap_username        | my_username             | Yes               |
   +-----------------------+-------------------------+-------------------+
   |  chap_password        | my_password             | Yes               |
   +-----------------------+-------------------------+-------------------+

   .. code-block:: ini

      [VMAX_ISCSI_DIAMOND]
      image_volume_cache_enabled = True
      volume_clear = zero
      volume_driver = cinder.volume.drivers.dell_emc.vmax.iscsi.VMAXISCSIDriver
      volume_backend_name = VMAX_ISCSI_DIAMOND
      san_ip = 10.10.10.10
      san_login = my_u4v_username
      san_password = my_u4v_password
      vmax_srp = SRP_1
      vmax_array = 000123456789
      vmax_port_groups = [OS-ISCSI-PG]
      use_chap_auth = True
      chap_username = my_username
      chap_password = my_password


Usage
-----

#. Using SYMCLI, enable CHAP authentication for a host initiator as described
   above, but do not set ``use_chap_auth``, ``chap_username`` or
   ``chap_password`` in ``cinder.conf``. Create a bootable volume.

   .. code-block:: console

      openstack volume create --size 1 \
                              --image <image_name> \
                              --type <volume_type> \
                              test

#. Boot instance named test_server using the volume created above:

   .. code-block:: console

      openstack server create --volume test \
                              --flavor m1.small \
                              --nic net-id=private \
                              test_server

#. Verify the volume operation succeeds but the boot instance fails as
   CHAP authentication fails.

#. Update the ``cinder.conf`` with ``use_chap_auth`` set to true and
   ``chap_username`` and ``chap_password`` set with the correct
   credentials.

#. Rerun ``openstack server create``

#. Verify that the boot instance operation ran correctly and the volume is
   accessible.

#. Verify that both the volume and boot instance operations ran successfully
   and the user is able to access the volume.


All Flash compression support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

On an All Flash array, the creation of any storage group has a compressed
attribute by default. Setting compression on a storage group does not mean
that all the devices will be immediately compressed. It means that for all
incoming writes compression will be considered. Setting compression ``off`` on
a storage group does not mean that all the devices will be uncompressed.
It means all the writes to compressed tracks will make these tracks
uncompressed.

.. note::

   This feature is applicable for All Flash 250F, 450F, 850F and
   Powermax 2000, 8000 arrays.

.. note::

   Since the release of the PowerMax in May 2018, ``Unisphere for PowerMax
   9.0.0.6`` can support ``Deduplication``. ``Compression`` and
   ``Deduplication`` go hand in hand so if ``Compression`` is enabled, so too
   is ``Deduplication``. Disabling ``Compression`` also disables
   ``Deduplication``. ``Deduplication`` is only available on the PowerMax
   array.

Use case 1 - Compression disabled create, attach, detach, and delete volume
---------------------------------------------------------------------------

#. Create a new volume type called ``VMAX_COMPRESSION_DISABLED``.
#. Set an extra spec ``volume_backend_name``.
#. Set a new extra spec ``storagetype:disablecompression = True``.
#. Create a new volume.
#. Check in Unisphere or symcli to see if the volume
   exists in storage group ``OS-<srp>-<servicelevel>-<workload>-CD-SG``, and
   compression is disabled on that storage group.
#. Attach the volume to an instance. Check in Unisphere or symcli to see if the
   volume exists in storage group
   ``OS-<shorthostname>-<srp>-<servicelevel/workload>-<portgroup>-CD``, and
   compression is disabled on that storage group.
#. Detach volume from instance. Check in Unisphere or symcli to see if the
   volume exists in storage group ``OS-<srp>-<servicelevel>-<workload>-CD-SG``,
   and compression is disabled on that storage group.
#. Delete the volume. If this was the last volume in the
   ``OS-<srp>-<servicelevel>-<workload>-CD-SG`` storage group,
   it should also be deleted.


Use case 2 - Retype from compression disabled to compression enabled
--------------------------------------------------------------------

#. Repeat steps 1-4 of Use case 1.
#. Create a new volume type. For example ``VMAX_COMPRESSION_ENABLED``.
#. Set extra spec ``volume_backend_name`` as before.
#. Set the new extra spec's compression as
   ``storagetype:disablecompression = False`` or DO NOT set this extra spec.
#. Retype from volume type ``VMAX_COMPRESSION_DISABLED`` to
   ``VMAX_COMPRESSION_ENABLED``.
#. Check in Unisphere or symcli to see if the volume exists in storage group
   ``OS-<srp>-<servicelevel>-<workload>-SG``, and compression is enabled on
   that storage group.

.. note::
   If extra spec ``storagetype:disablecompression`` is set on a hybrid, it is
   ignored because compression is not a feature on a VMAX3 hybrid.


Volume replication support
~~~~~~~~~~~~~~~~~~~~~~~~~~

Configure the source and target arrays
--------------------------------------

#. Configure an SRDF group between the chosen source and target
   arrays for the VMAX cinder driver to use. The source array must correspond
   with the 'vmax_array' entry in the cinder.conf (or the ``<Array>`` entry
   in the VMAX XML file for legacy setups).
#. Select both the director and the ports for the SRDF emulation to use on
   both sides. Bear in mind that network topology is important when choosing
   director endpoints. Supported modes are `Synchronous`, `Asynchronous`,
   and `Metro`.

   .. note::

      If the source and target arrays are not managed by the same Unisphere
      server (that is, the target array is remotely connected to server -
      for example, if you are using embedded management), in the event of a
      full disaster scenario (i.e. the primary array is completely lost and
      all connectivity to it is gone), the Unisphere server would no longer
      be able to contact the target array. In this scenario, the volumes would
      be automatically failed over to the target array, but administrator
      intervention would be required to either; configure the target (remote)
      array as local to the current Unisphere server (if it is a stand-alone
      server), or enter the details of a second Unisphere server to the
      ``cinder.conf``, which is locally connected to the target array (for
      example, the embedded management Unisphere server of the target array),
      and restart the cinder volume service.

   .. note::

      If you are setting up an SRDF/Metro configuration, it is recommended that
      you configure a Witness or vWitness for bias management. Please see
      https://www.emc.com/collateral/technical-documentation/h14556-vmax3-srdf-metro-overview-and-best-practices-tech-note.pdf

#. Enable replication in ``/etc/cinder/cinder.conf``.
   To enable the replication functionality in VMAX cinder driver, it is
   necessary to create a replication volume-type. The corresponding
   back-end stanza in the ``cinder.conf`` for this volume-type must then
   include a ``replication_device`` parameter. This parameter defines a
   single replication target array and takes the form of a list of key
   value pairs.

   .. code-block:: console

      enabled_backends = VMAX_FC_REPLICATION
      [VMAX_FC_REPLICATION]
      volume_driver = cinder.volume.drivers.dell_emc.vmax_fc.VMAXFCDriver
      san_ip = 10.10.10.10
      san_login = my_u4v_username
      san_password = my_u4v_password
      vmax_srp = SRP_1
      vmax_array = 000123456789
      vmax_port_groups = [OS-FC-PG]
      use_chap_auth = True
      chap_username = my_username
      chap_password = my_password
      volume_backend_name = VMAX_FC_REPLICATION
      replication_device = target_device_id:000197811111,
                           remote_port_group:os-failover-pg,
                           remote_pool:SRP_1,
                           rdf_group_label: 28_11_07,
                           allow_extend:False,
                           mode:Metro,
                           metro_use_bias:False,
                           allow_delete_metro:False

      .. note::

         ``replication_device`` key value pairs will need to be on the same line
         (separated by commas) in cinder.conf.  They are displayed on separated lines
         above for readiblity.

   * ``target_device_id`` is a unique VMAX array serial number of the target
     array. For full failover functionality, the source and target VMAX arrays
     must be discovered and managed by the same U4V server.

   * ``remote_port_group`` is the name of a VMAX port group that has been
     pre-configured to expose volumes managed by this backend in the event
     of a failover. Make sure that this portgroup contains either all FC or
     all iSCSI port groups (for a given back end), as appropriate for the
     configured driver (iSCSI or FC).

   * ``remote_pool`` is the unique pool name for the given target array.

   * ``rdf_group_label`` is the name of a VMAX SRDF group that has been pre-configured
     between the source and target arrays.

   * ``allow_extend`` is a flag for allowing the extension of replicated volumes.
     To extend a volume in an SRDF relationship, this relationship must first be
     broken, both the source and target volumes are then independently extended,
     and then the replication relationship is re-established. If not explicitly
     set, this flag defaults to ``False``.

     .. note::
        As the SRDF link must be severed, due caution should be exercised when
        performing this operation. If absolutely necessary, only one source and
        target pair should be extended at a time.

     .. note::
        It is not currently possible to extend SRDF/Metro protected volumes.

   * ``mode`` is the required replication mode. Options are 'Synchronous',
     'Asynchronous', and 'Metro'. This defaults to 'Synchronous'.

   * ``metro_use_bias`` is a flag to indicate if 'bias' protection should be
     used instead of Witness. This defaults to False.

   * ``allow_delete_metro`` is a flag to indicate if metro devices can be deleted.
     All Metro devices in an RDF group need to be managed together, so in order to delete
     one of the pairings, the whole group needs to be first suspended. Because of this,
     we require this flag to be explicitly set. This flag defaults to False.


   .. note::
      Service Level and Workload: An attempt will be made to create a storage
      group on the target array with the same service level and workload combination
      as the primary. However, if this combination is unavailable on the target
      (for example, in a situation where the source array is a Hybrid, the target array
      is an All Flash, and an All Flash incompatible service level like Bronze is
      configured), no service level will be applied.

   .. note::
      The VMAX cinder drivers can support a single replication target per
      back-end, that is we do not support Concurrent SRDF or Cascaded SRDF.
      Ensure there is only a single ``replication_device`` entry per
      back-end stanza.

#. Create a ``replication-enabled`` volume type. Once the
   ``replication_device`` parameter has been entered in the VMAX
   backend entry in the ``cinder.conf``, a corresponding volume type
   needs to be created ``replication_enabled`` property set. See
   above ``Setup VMAX drivers`` for details.

   .. code-block:: console

      # openstack volume type set --property replication_enabled="<is> True" \
                            VMAX_FC_REPLICATION


Volume replication interoperability with other features
-------------------------------------------------------

Most features are supported, except for the following:

* Replication Group operations are available for volumes in Synchronous mode only.

* Storage-assisted retype operations on replication-enabled VMAX volumes
  (moving from a non-replicated type to a replicated-type and vice-versa.
  Moving to another service level/workload combination, for example) are
  not supported.

* It is not currently possible to extend SRDF/Metro protected volumes.
  If a bigger volume size is required for a SRDF/Metro protected volume, this can be
  achieved by cloning the original volume and choosing a larger size for the new
  cloned volume.

* The image volume cache functionality is supported (enabled by setting
  ``image_volume_cache_enabled = True``), but one of two actions must be taken
  when creating the cached volume:

  * The first boot volume created on a backend (which will trigger the
    cached volume to be created) should be the smallest necessary size.
    For example, if the minimum size disk to hold an image is 5GB, create
    the first boot volume as 5GB.
  * Alternatively, ensure that the ``allow_extend`` option in the
    ``replication_device parameter`` is set to ``True`` (Please note that it is
    not possible to extend SRDF/Metro protected volumes).

  This is because the initial boot volume is created at the minimum required
  size for the requested image, and then extended to the user specified size.


Failover host
-------------

In the event of a disaster, or where there is required downtime, upgrade
of the primary array for example, the administrator can issue the failover
host command to failover to the configured target:

.. code-block:: console

   # cinder failover-host cinder_host@VMAX_FC_REPLICATION

If the primary array becomes available again, you can initiate a failback
using the same command and specifying ``--backend_id default``:

.. code-block:: console

   # cinder failover-host cinder_host@VMAX_FC_REPLICATION --backend_id default

.. note::

   Failover and Failback operations are not applicable in Metro configurations.


Asynchronous and Metro replication management groups
----------------------------------------------------

Asynchronous and Metro volumes in an RDF session, i.e. belonging to an SRDF
group, must be managed together for RDF operations (although there is a
``consistency exempt`` option for creating and deleting pairs in an Async
group). To facilitate this management, we create an internal RDF management
storage group on the backend. It is crucial for correct management that the
volumes in this storage group directly correspond to the volumes in the RDF
group. For this reason, it is imperative that the RDF group specified in the
``cinder.conf`` is for the exclusive use by this cinder backend.


Metro support
-------------

SRDF/Metro is a High Availabilty solution. It works by masking both sides of
the RDF relationship to the host, and presenting all paths to the host,
appearing that they all point to the one device. In order to do this,
there needs to be multipath software running to manage writing to the
multiple paths.


Volume retype -  storage assisted volume migration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Volume retype with storage assisted migration is supported now for
VMAX3 arrays. Cinder requires that for storage assisted migration, a
volume cannot be retyped across backends. For using storage assisted volume
retype, follow these steps:

#. For migrating a volume from one Service Level or Workload combination to
   another, use volume retype with the migration-policy to on-demand. The
   target volume type should have the same volume_backend_name configured and
   should have the desired pool_name to which you are trying to retype to
   (please refer to ``Setup VMAX Drivers`` for details).

   .. code-block:: console

      $ cinder retype --migration-policy on-demand <volume> <volume-type>


Generic volume group support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Generic volume group operations are performed through the CLI using API
version 3.1x of the cinder API. Generic volume groups are multi-purpose
groups which can be used for various features. The VMAX plugin supports
consistent group snapshots and replication groups. Consistent group
snapshots allows the user to take group snapshots which
are consistent based on the group specs. Replication groups allow for/
tenant facing APIs to enable and disable replication, and to failover
and failback, a group of volumes. Generic volume groups have replaced
the deprecated consistency groups.

Consistent group snapshot
-------------------------

To create a consistent group snapshot, set a group-spec, having the key
``consistent_group_snapshot_enabled`` set to ``<is> True`` on the group.

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-type-key GROUP_TYPE set consistent_group_snapshot_enabled="<is> True"

Similarly the same key should be set on any volume type which is specified
while creating the group.

.. code-block:: console

   # openstack volume type set --property replication_enabled="<is> True" /
                           VMAX_REPLICATION

If this key is not set on the group-spec or volume type, then the generic
volume group will be created/managed by cinder (not the VMAX plugin).

.. note::

   The consistent group snapshot should not be confused with the VMAX
   consistency group which is an SRDF construct.

Replication groups
------------------

As with Consistent group snapshot ``consistent_group_snapshot_enabled`` should
be set to true on the group and the volume type for replication groups.
Only Synchronous replication
is supported for use with Replication Groups. When a volume is created into a
replication group, replication is on by default. The ``disable_replication``
api suspends I/O traffic on the devices, but does NOT remove replication for
the group. The ``enable_replication`` api resumes I/O traffic on the RDF
links. The "failover_group" api allows a group to be failed over and back
without failing over the entire host. See below for usage.

.. note::

   A generic volume group can be both consistent group snapshot enabled and
   consistent group replication enabled.

Storage Group Names
-------------------

Storage groups are created on the VMAX as a result of creation of generic
volume groups. These storage groups follow a different naming convention
and are of the following format depending upon whether the groups have a
name.

.. code-block:: text

   TruncatedGroupName_GroupUUID or GroupUUID

Group type operations
---------------------

- Create a group type

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-type-create GROUP_TYPE

- Show a group type

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-type-show GROUP_TYPE

- List group types

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-type-list

- Delete group type

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-type-delete GROUP_TYPE

- Set/unset a group spec

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-type-key GROUP_TYPE set consistent_group_snapshot_enabled="<is> True"

- List group types and group specs:

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-specs-list

Group operations
----------------

- Create a group:

.. code-block:: console

   cinder --os-volume-api-version 3.13 group-create --name GROUP GROUP_TYPE VOLUME_TYPE1,VOLUME_TYPE2

- Show a group:

.. code-block:: console

   cinder --os-volume-api-version 3.13 group-show GROUP

- List all groups:

.. code-block:: console

   cinder --os-volume-api-version 3.13 group-list

- Create a volume and add it to a group at the time of creation:

.. code-block:: console

   cinder --os-volume-api-version 3.13 create --volume-type VOLUME_TYPE1 --group-id GROUP_ID 1

- Modify a group to add or remove volumes:

.. code-block:: console

   cinder --os-volume-api-version 3.13 group-update --add-volumes UUID1,UUID2 --remove-volumes UUID3,UUID4 GROUP

- Delete a group

.. code-block:: console

   cinder --os-volume-api-version 3.13 group-delete --delete-volumes GROUP

Group snapshot operations
-------------------------

- Create a group snapshot:

.. code-block:: console

   cinder --os-volume-api-version 3.14 group-snapshot-create --name GROUP_SNAPSHOT GROUP

- Delete group snapshot(s):

.. code-block:: console

   cinder --os-volume-api-version 3.14 group-snapshot-delete GROUP_SNAPSHOT

- Create a group from a group snapshot:

.. code-block:: console

   $ cinder --os-volume-api-version 3.14 group-create-from-src --group-snapshot GROUP_SNAPSHOT --name GROUP

- Create a group from a source snapshot:

.. code-block:: console

   $ cinder --os-volume-api-version 3.14 group-create-from-src --source-group SOURCE_GROUP --name GROUP

Group replication operations
----------------------------

- Enable group replication

.. code-block:: console

   cinder --os-volume-api-version 3.38 group-enable-replication GROUP

- Disable group replication

.. code-block:: console

   cinder --os-volume-api-version 3.38 group-disable-replication GROUP

- Failover group

.. code-block:: console

   cinder --os-volume-api-version 3.38 group-failover-replication GROUP

- Failback group

.. code-block:: console

   cinder --os-volume-api-version 3.38 group-failover-replication GROUP /
       --secondary-backend-id default


Oversubscription support
~~~~~~~~~~~~~~~~~~~~~~~~

Please refer to the following:
https://docs.openstack.org/cinder/latest/admin/blockstorage-over-subscription.html


Live Migration support
~~~~~~~~~~~~~~~~~~~~~~

Non-live migration (sometimes referred to simply as 'migration'). The instance
is shut down for a period of time to be moved to another hypervisor. In this
case, the instance recognizes that it was rebooted. Live migration
(or 'true live migration'). Almost no instance downtime. Useful when the
instances must be kept running during the migration. The different types
of live migration are:

- Shared storage-based live migration. Both hypervisors have access to shared
  storage.

- Block live migration. No shared storage is required. Incompatible with
  read-only devices such as CD-ROMs and Configuration Drive (config_drive).

- Volume-backed live migration. Instances are backed by volumes rather than
  ephemeral disk.  For VMAX volume-backed live migration, shared storage
  is required.

The VMAX driver supports shared volume-backed live migration.

Architecture
------------

In VMAX, A volume cannot belong to two or more FAST storage groups at the
same time. To get around this limitation we leverage both cascaded storage
groups and a temporary non FAST storage group.

A volume can remain 'live' if moved between masking views that have the same
initiator group and port groups which preserves the host path.

During live migration, the following steps are performed by the VMAX plugin
on the volume:

#. Within the originating masking view, the volume is moved from the FAST
   storage group to the non-FAST storage group within the parent storage
   group.
#. The volume is added to the FAST storage group within the destination
   parent storage group of the destination masking view. At this point the
   volume belongs to two storage groups.
#. One of two things happens:

   - If the connection to the destination instance is successful, the volume
     is removed from the non-FAST storage group in the originating masking
     view, deleting the storage group if it contains no other volumes.
   - If the connection to the destination instance fails, the volume is
     removed from the destination storage group, deleting the storage group,
     if empty. The volume is reverted back to the original storage group.


Live migration configuration
----------------------------

Please refer to the following for more information:

https://docs.openstack.org/nova/queens/admin/live-migration-usage.html
https://docs.openstack.org/nova/queens/admin/configuring-migrations.html

.. note::

   OpenStack Oslo uses an open standard for messaging middleware known as AMQP.
   This messaging middleware (the RPC messaging system) enables the OpenStack
   services that run on multiple servers to talk to each other.
   By default, the RPC messaging client is set to timeout after 60 seconds,
   meaning if any operation you perform takes longer than 60 seconds to
   complete the operation will timeout and fail with the ERROR message
   "Messaging Timeout: Timed out waiting for a reply to message ID [message_id]"

   If this occurs, increase the ``rpc_response_timeout`` flag value in
   ``cinder.conf`` and ``nova.conf`` on all Cinder and Nova nodes and restart
   the services.

   What to change this value to will depend entirely on your own environment,
   you might only need to increase it slightly, or if your environment is
   under heavy network load it could need a bit more time than normal. Fine
   tuning is required here, change the value and run intensive operations to
   determine if your timeout value matches your environment requirements.

   At a minimum please set ``rpc_response_timeout`` to ``240``, but this will
   need to be raised if high concurrency is a factor. This should be
   sufficient for all cinder backup commands also.


System configuration
--------------------

``NOVA-INST-DIR/instances/`` (for example, ``/opt/stack/data/nova/instances``)
has to be mounted by shared storage. Ensure that NOVA-INST-DIR (set with
state_path in the nova.conf file) is the same on all hosts.

#. Configure your DNS or ``/etc/hosts`` and ensure it is consistent across all
   hosts. Make sure that the three hosts can perform name resolution with each
   other. As a test, use the ping command to ping each host from one another.

   .. code-block:: console

      $ ping HostA
      $ ping HostB
      $ ping HostC

#. Export NOVA-INST-DIR/instances from HostA, and ensure it is readable and
   writable by the Compute user on HostB and HostC. Please refer to the
   relevant OS documentation for further details.
   e.g. https://help.ubuntu.com/lts/serverguide/network-file-system.html

#. On all compute nodes, enable the 'execute/search' bit on your shared
   directory to allow qemu to be able to use the images within the
   directories. On all hosts, run the following command:

   .. code-block:: console

       $ chmod o+x NOVA-INST-DIR/instances

.. note::

   If migrating from compute to controller, make sure to run step two above on
   the controller node to export the instance directory.


Use case
--------

For our use case shown below, we have three hosts with host names HostA, HostB
and HostC. HostA is the compute node while HostB and HostC are the compute
nodes. The following were also used in live migration.

- 2 gb bootable volume using the cirros image.
- Instance created using the 2gb volume above with a flavor m1.small using
  2048 RAM, 20GB of Disk and 1 VCPU.

#. Create a bootable volume.

   .. code-block:: console

      $ openstack volume create --size 2 \
                                --image cirros-0.3.5-x86_64-disk \
                                --volume_lm_1

#. Launch an instance using the volume created above on HostB.

   .. code-block:: console

      $ openstack server create --volume volume_lm_1 \
                                --flavor m1.small \
                                --nic net-id=private \
                                --security-group default \
                                --availability-zone nova:HostB \
                                server_lm_1

#. Confirm on HostB has the instance created by running:

   .. code-block:: console

      $ openstack server show server_lm_1 | grep "hypervisor_hostname\|instance_name"
        | OS-EXT-SRV-ATTR:hypervisor_hostname | HostB
        | OS-EXT-SRV-ATTR:instance_name | instance-00000006

#. Confirm, through virsh using the instance_name returned in step 3
   (instance-00000006), on HostB that the instance is created using:

   .. code-block:: console

      $ virsh list --all

      Id   Name                  State
      --------------------------------
      1    instance-00000006     Running

#. Migrate the instance from HostB to HostA with:

   .. code-block:: console

      $ openstack server migrate --live HostA \
                                 server_lm_1

#. Run the command on step 3 above when the instance is back in available
   status. The hypervisor should be on Host A.

#. Run the command on Step 4 on Host A to confirm that the instance is
   created through virsh.


Manage and Unmanage Volumes
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Managing volumes in OpenStack is the process whereby a volume which exists
on the storage device is imported into OpenStack to be made available for use
in the OpenStack environment.  For a volume to be valid for managing into
OpenStack, the following prerequisites must be met:

- The volume exists in a Cinder managed pool

- The volume is not part of a Masking View

- The volume is not part of an SRDF relationship

- The volume is configured as a TDEV (thin device)

- The volume is set to FBA emulation

- The volume must a whole GB e.g. 5.5GB is not a valid size

- The volume cannot be a snapvx target


For a volume to exist in a Cinder managed pool, it must reside in in the same
Storage Resource Pool (SRP) as the backend which is configured for use in
OpenStack. Specifying the pool correctly can be entered manually as it follows
the same format:

.. code-block:: console

   Pool format: <service_level>+<workload_type>+<srp>+<array_id>
   Pool example 1: Diamond+DSS+SRP_1+111111111111
   Pool example 2: Diamond+SRP_1+111111111111


.. table:: **Pool values**

 +----------------+-------------------------------------------------------------+
 |  Key           | Value                                                       |
 +================+=============================================================+
 |  service_level | The service level of the volume to be managed               |
 +----------------+-------------------------------------------------------------+
 |  workload      | The workload of the volume to be managed                    |
 +----------------+-------------------------------------------------------------+
 |  SRP           | The Storage Resource Pool configured for use by the backend |
 +----------------+-------------------------------------------------------------+
 |  array_id      | The VMAX serial number (12 digit numerical)                 |
 +----------------+-------------------------------------------------------------+


Manage Volumes
--------------

With your pool name defined you can now manage the volume into OpenStack, this
is possible with the CLI command ``cinder manage``. The bootable parameter is
optional in the command, if the volume to be managed into OpenStack is not
bootable leave this parameter out. OpenStack will also determine the size of
the value when it is managed so there is no need to specify the volume size.

Command format:

.. code-block:: console

   $ cinder manage --name <new_volume_name> --volume-type <vmax_vol_type> \
     --availability-zone <av_zone> <--bootable> <host> <identifier>

Command Example:

.. code-block:: console

   $ cinder manage --name vmax_managed_volume --volume-type VMAX_ISCSI_DIAMOND \
     --availability-zone nova demo@VMAX_ISCSI_DIAMOND#Diamond+SRP_1+111111111111 031D8

After the above command has been run, the volume will be available for use in
the same way as any other OpenStack VMAX volume.

.. note::

   An unmanaged volume with a prefix of 'OS-' in its identifier name cannot be
   managed into OpenStack, as this is a reserved keyword for managed volumes.
   If the identifier name has this prefix, an exception will be thrown by the
   VMAX driver on a manage operation.


Managing Volumes with Replication Enabled
-----------------------------------------

Whilst it is not possible to manage volumes into OpenStack that are part of a
SRDF relationship, it is possible to manage a volume into OpenStack and
enable replication at the same time. This is done by having a replication
enabled VMAX volume type (for more information see section Volume Replication)
during the manage volume process you specify the replication volume type as
the chosen volume type. Once managed, replication will be enabled for that
volume.


Unmanage Volume
---------------

Unmanaging a volume is not the same as deleting a volume. When a volume is
deleted from OpenStack, it is also deleted from the VMAX at the same time.
Unmanaging a volume is the process whereby a volume is removed from OpenStack
but it remains for further use on the VMAX. The volume can also be managed
back into OpenStack at a later date using the process discussed in the
previous section. Unmanaging volume is carried out using the Cinder
unmanage CLI command:

Command format:

.. code-block:: console

   $ cinder unmanage <volume_name/volume_id>

Command example:

.. code-block:: console

   $ cinder unmanage vmax_test_vol

Once unmanaged from OpenStack, the volume can still be retrieved using its
device ID or OpenStack volume ID. Within Unisphere you will also notice that
the 'OS-' prefix has been removed, this is another visual indication that
the volume is no longer managed by OpenStack.


Manage/Unmanage Snapshots
~~~~~~~~~~~~~~~~~~~~~~~~~

Users can manage VMAX SnapVX snapshots into OpenStack if the source volume
already exists in Cinder. Similarly, users will be able to unmanage OpenStack
snapshots to remove them from Cinder but keep them on the storage backend.

Set-up, restrictions and requirements:

#. No additional settings or configuration is required to support this
   functionality.

#. Manage/Unmanage snapshots requires SnapVX functionality support on VMAX.

#. Manage/Unmanage Snapshots in OpenStack Cinder is only supported at present
   through Cinder CLI commands.

#. It is only possible to manage or unmanage one snapshot at a time in Cinder.

Manage SnapVX Snapshot
----------------------

It is possible to manage VMAX SnapVX snapshots into OpenStack, where the
source volume from which the snapshot is taken already exists in, and is
managed by OpenStack Cinder. The source volume may have been created in
OpenStack Cinder, or it may have been managed in to OpenStack Cinder also.
With the support of managing SnapVX snapshots included in OpenStack Queens,
the restriction around managing SnapVX source volumes has been removed.

.. note::

   It is not possible to manage into OpenStack SnapVX linked target volumes,
   or volumes which exist in a replication session.


Requirements/Restrictions:

#. The SnapVX source volume must be present in and managed by Cinder.

#. The SnapVX snapshot name must not begin with ``OS-``.

#. The SnapVX snapshot source volume must not be in a failed-over state.

#. Managing a SnapVX snapshot will only be allowed if the snapshot has no
   linked target volumes.


Command Structure:

#. Identify your SnapVX snapshot for management on the VMAX, note the name.

#. Ensure the source volume is already managed into OpenStack Cinder, note
   the device ID.

#. Using the Cinder CLI, use the following command structure to manage a
   Snapshot into OpenStack Cinder:


.. code-block:: console

   $ cinder snapshot-manage --id-type source-name
                            [--name <name>]
                            [--description <description>]
                            [--metadata [<key=value> [<key=value> ...]]]
                            <device_id> <identifier>

Positional arguments:

- <device_id> - the VMAX device id

- <identifier> - Name of existing snapshot

Optional arguments:

- --name <name> - Snapshot name (Default=None)

- --description <description> - Snapshot description (Default=None)

- --metadata [<key=value> [<key=value> ...]]
  Metadata key=value pairs (Default=None)

Example:

.. code-block:: console

   $ cinder snapshot-manage --name SnapshotManaged \
                            --description "Managed Queens Feb18" \
                            0021A VMAXSnapshot

Where:

- The name in OpenStack after managing the SnapVX snapshot will be
  ``SnapshotManaged``.

- The snapshot will have the description ``Managed Queens Feb18``.

- The source volume device ID is ``0021A``.

- The name of the SnapVX snapshot on the VMAX backend is ``VMAXSnapshot``.

Outcome:

After the process of managing the Snapshot has completed, the SnapVX snapshot
on the VMAX backend will be prefixed by the letters ``OS-``, leaving the
snapshot in this example named ``OS-VMAXSnapshot``. The associated snapshot
managed by Cinder will be present for use under the name ``SnapshotManaged``.


Unmanage Cinder Snapshot
~~~~~~~~~~~~~~~~~~~~~~~~

Unmanaging a snapshot in Cinder is the process whereby the snapshot is removed
from and no longer managed by Cinder, but it still exists on the storage
backend. Unmanaging a SnapVX snapshot in OpenStack Cinder follows this
behaviour, whereby after unmanaging a VMAX SnapVX snapshot from Cinder, the
snapshot is removed from OpenStack but is still present for use on the VMAX
backend.

Requirements/Restrictions:

- The SnapVX source volume must not be in a failed over state.

Command Structure:

Identify the SnapVX snapshot you want to unmanage from OpenStack cinder, note
the snapshot name or ID as specified by Cinder. Using the Cinder CLI use the
following command structure to unmanage the SnapVX snapshot from Cinder:

.. code-block:: console

   $ cinder snapshot-unmanage <snapshot>

Positional arguments:

- <snapshot> - Cinder snapshot name or ID.

Example:

.. code-block:: console

   $ cinder snapshot-unmanage SnapshotManaged

Where:

- The SnapVX snapshot name in OpenStack Cinder is SnapshotManaged.

After the process of unmanaging the SnapVX snapshot in Cinder, the snapshot on
the VMAX backend will have the ``OS-`` prefix removed to indicate it is no
longer OpenStack managed. In the example above, the snapshot after unmanaging
from OpenStack will be named ``VMAXSnapshot`` on the storage backend.


Restore From Snapshot
---------------------

.. note::

   This feature is only available from ``Unisphere REST 9.0.0.6`` onward

Restore from snapshot or revert a volume to a snapshot, restores the data from
snapshot to the volume i.e. the volume will be overwritten with the point in
time data from the snapshot. The revert is not permitted when the volume and
snapshot are not the same size, only works with the most recent snapshot and
when the volume is not attached.


Online Device Expansion for Replicated Volumes
----------------------------------------------

.. note::

   This feature is only available from ``Unisphere REST 9.0.0.6`` onward and
   the array must be running HyperMaxOS 5978 or later.

Device expansion has been enhanced to support RDF devices and devices with
snapVX sessions.
