==================================
Dell EMC VMAX iSCSI and FC drivers
==================================

The Dell EMC VMAX drivers, ``VMAXISCSIDriver`` and ``VMAXFCDriver``, support
the use of Dell EMC VMAX storage arrays with Block Storage. They both provide
equivalent functions and differ only in support for their respective host
attachment methods.

The drivers perform volume operations by communicating with the back-end VMAX
storage. They use the Requests HTTP library to communicate with a Unisphere
for VMAX instance, using a RESTAPI interface in the backend to perform VMAX
storage operations.

System requirements
~~~~~~~~~~~~~~~~~~~

The Cinder driver supports the VMAX-3 series and VMAX All-Flash arrays.

Solutions Enabler 8.4.0.7 or later, and Unisphere for VMAX 8.4.0.15 or later
are required.

You can download Solutions Enabler and Unisphere from the Dell EMC's support
web site (login is required). See the ``Solutions Enabler 8.4.0 Installation
and Configuration Guide`` and ``Unisphere for VMAX 8.4.0 Installation Guide``
at ``support.emc.com``.

Required VMAX software suites for OpenStack
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There are five Software Suites available for the VMAX All Flash and Hybrid:

- Base Suite
- Advanced Suite
- Local Replication Suite
- Remote Replication Suite
- Total Productivity Pack

OpenStack requires the Advanced Suite and the Local Replication Suite
or the Total Productivity Pack (it includes the Advanced Suite and the
Local Replication Suite) for the VMAX All Flash and Hybrid.

Using the Remote Replication functionality will also require the Remote
Replication Suite.

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
-  Create and delete generice volume group snapshot
-  Modify generic volume group (add and remove volumes)
-  Create generic volume group from source
-  Live Migration
-  Volume replication

VMAX drivers also support the following features:

-  Dynamic masking view creation
-  Dynamic determination of the target iSCSI IP address
-  iSCSI multipath support
-  Oversubscription
-  Service Level support
-  SnapVX support
-  Compression support(All Flash only)

.. note::

   VMAX All Flash array with Solutions Enabler 8.3.0.11 or later have
   compression enabled by default when associated with Diamond Service Level.
   This means volumes added to any newly created storage groups will be
   compressed.

#. Install iSCSI Utilities (for iSCSI drivers only).

   #. Download and configure the Cinder node as an iSCSI initiator.
   #. Install the ``open-iscsi`` package.

      -  On Ubuntu:

         .. code-block:: console

            # apt-get install open-iscsi

      -  On openSUSE:

         .. code-block:: console

            # zypper install open-iscsi

      -  On Red Hat Enterprise Linux, CentOS, and Fedora:

         .. code-block:: console

            # yum install scsi-target-utils.x86_64

   #. Enable the iSCSI driver to start automatically.

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

#. Configure Block Storage

   Add the following entries to ``/etc/cinder/cinder.conf``:

   .. code-block:: ini

      enabled_backends = CONF_GROUP_ISCSI, CONF_GROUP_FC

      [CONF_GROUP_ISCSI]
      volume_driver = cinder.volume.drivers.dell_emc.vmax.iscsi.VMAXISCSIDriver
      cinder_dell_emc_config_file = /etc/cinder/cinder_dell_emc_config_CONF_GROUP_ISCSI.xml
      volume_backend_name = ISCSI_backend


      [CONF_GROUP_FC]
      volume_driver = cinder.volume.drivers.dell_emc.vmax.fc.VMAXFCDriver
      cinder_dell_emc_config_file = /etc/cinder/cinder_dell_emc_config_CONF_GROUP_FC.xml
      volume_backend_name = FC_backend

   In this example, two back-end configuration groups are enabled:
   ``CONF_GROUP_ISCSI`` and ``CONF_GROUP_FC``. Each configuration group has a
   section describing unique parameters for connections, drivers, the
   ``volume_backend_name``, and the name of the EMC-specific configuration file
   containing additional settings. Note that the file name is in the format
   ``/etc/cinder/cinder_dell_emc_config_[confGroup].xml``.

   Once the ``cinder.conf`` and EMC-specific configuration files have been
   created, :command:`openstack` commands need to be issued in order to
   create and associate OpenStack volume types with the declared
   ``volume_backend_names``:

   Additionally, each volume type will need an associated ``pool_name`` - an
   extra specification indicating the service level/ workload combination to
   be used for that volume type.

   There is also the option to assign a port group to a volume type by
   setting the ``storagetype:portgroupname`` extra specification.

``ServiceLevel``
   The Service Level manages the underlying storage to provide expected
   performance. Setting the ``ServiceLevel`` to ``NONE`` means that non-FAST
   managed storage groups will be created instead (storage groups not
   associated with any service level).

``Workload``
   When a workload type is added, the latency range is reduced due to the
   added information. Setting the ``Workload`` to ``NONE`` means the latency
   range will be the widest for its Service Level type. Please note that you
   cannot set a Workload without a Service Level.

.. note::

   Run the command cinder get-pools --detail to query for the pool
   information. This should list all the available Service Level and Workload
   combinations available for the SRP as pools belonging to the same backend.
   You can create many volume types for different service level and workload
   types using the same backend.

``Port Groups``
   Port groups refer to VMAX port groups that have been pre-configured to
   expose volumes managed by this backend. Each supplied port group should
   have sufficient number and distribution of ports (across directors and
   switches) as to ensure adequate bandwidth and failure protection for the
   volume connections. PortGroups can contain one or more port groups of
   either iSCSI or FC ports. Make sure that any PortGroups provided contain
   either all FC or all iSCSI port groups (for a given back end), as
   appropriate for the configured driver (iSCSI or FC). Port groups can be
   assigned as an extra spec, or can be provided in the xml file.
   Port groups provided as the extra spec are selected first.

.. note::

   Create as many volume types as the number of Service Level and Workload
   (available) combinations which you are going to use for provisioning
   volumes. The pool_name is the additional property which has to be set and
   is of the format: ``<ServiceLevel>+<Workload>+<SRP>+<Array ID>``. This
   can be obtained from the output of the ``cinder get-pools--detail``.

.. code-block:: console

   $ openstack volume type create VMAX_ISCI_SILVER_OLTP
   $ openstack volume type set --property volume_backend_name=ISCSI_backend \
                               --property pool_name=Silver+OLTP+SRP_1+000197800123 \
                               --property storagetype:portgroupname=OS-PG2 \
                               VMAX_ ISCI_SILVER_OLTP
   $ openstack volume type create VMAX_FC_DIAMOND_DSS
   $ openstack volume type set --property volume_backend_name=FC_backend \
                               --property pool_name=Diamond+DSS+SRP_1+000197800123 \
                                --property port_group_name=OS-PG1 \
                               VMAX_FC_DIAMOND_DSS


By issuing these commands, the Block Storage volume type
``VMAX_ISCSI_SILVER_OLTP`` is associated with the ``ISCSI_backend``, a Silver
Service Level, and an OLTP workload.

The type ``VMAX_FC_DIAMOND_DSS`` is associated with the ``FC_backend``, a
Diamond Service Level, and a DSS workload.

.. note::

   VMAX Hybrid supports Optimized, Diamond, Platinum, Gold, Silver, Bronze,
   and NONE service levels. VMAX All Flash supports Diamond and NONE. Both
   support DSS_REP, DSS, OLTP_REP, OLTP, and NONE workloads.

#. Create an XML file

   Create the ``/etc/cinder/cinder_dell_emc_config_CONF_GROUP_ISCSI.xml``
   file. You do not need to restart the service for this change.

   Add the following lines to the XML file:


.. code-block:: xml

   <?xml version="1.0" encoding="UTF-8" ?>
   <EMC>
      <RestServerIp>1.1.1.1</RestServerIp>
      <RestServerPort>8443</RestServerPort>
      <RestUserName>smc</RestUserName>
      <RestPassword>smc</RestPassword>
      <PortGroups>
         <PortGroup>OS-PORTGROUP1-PG</PortGroup>
         <PortGroup>OS-PORTGROUP2-PG</PortGroup>
      </PortGroups>
      <Array>111111111111</Array>
      <SRP>SRP_1</SRP>
      <SSLVerify>/path/to/sslcert</SSLVerify>
   </EMC>

Where:

``RestServerIp``
   IP address of the Unisphere server.

``RestServerPort``
   Port number of the Unisphere server.

``RestUserName`` and ``RestPassword``
   Credentials for the Unisphere server.

``PortGroups``
   Supplies the names of VMAX port groups that have been pre-configured to
   expose volumes managed by this array. Port groups can be supplied in the
   XML file, or can be specified as an extra spec on a volume type for more
   control. Please see above section on port groups. When a dynamic masking
   view is created by the VMAX driver, if there is no port group specified
   as an extra specification, the port group is chosen randomly from the
   PortGroup list, to evenly distribute load across the set of groups
   provided.

``Array``
   Unique VMAX array serial number.

``SRP``
   The name of the storage resource pool for the given array.

``SSLVerify``
   The path to the ``ca_cert.pem`` file of the Unisphere instance below, or
   ``True`` if the SSL cert has been added to the bundle - see ``SSL support``.


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

      # openssl s_client -showcerts -connect my_unisphere_host:8443 </dev/null 2>/dev/null|openssl x509 -outform PEM >ca_cert.pem

   Where ``my_unisphere_host`` is the hostname of the unisphere instance and
   ``ca_cert.pem`` is the name of the .pem file.

#. Add this path to the <SSLVerify> tag in
   ``/etc/cinder/cinder_dell_emc_config_<conf_group>.xml``

   .. code-block:: console

      <SSLVerify>/path/to/ca_cert.pem</SSLVerify>

   ``OR`` follow the steps below:

#. OPTIONAL (if step 2 completed): Copy the pem file to the system certificate
   directory:

   .. code-block:: console

      # cp ca_cert.pem /usr/share/ca-certificates/ca_cert.crt

#. OPTIONAL: Update CA certificate database with the following commands:

   .. code-block:: console

      # sudo dpkg-reconfigure ca-certificates

   .. note::

      Check that the new ``ca_cert.crt`` will activate by selecting ask on the
      dialog. If it is not enabled for activation, use the down and up keys to
      select, and the space key to enable or disable.

      .. code-block:: console

         # sudo update-ca-certificates

#. Ensure ``<SSLVerify>`` tag in
   ``/etc/cinder/cinder_dell_emc_config_<conf_group>.xml`` is set to True OR
   the path defined in step 1.


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

         $ openssl s_client --connect {ip_address}:{port} -CAfile {cert_name}.pem -verify 9

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
   explicitly enabled . see the compression and replication sections below.

Interval and Retries
--------------------

By default, ``interval`` and ``retries`` are ``3`` seconds and ``200`` retries
respectively. These determine how long (``interval``) and how many times
(``retries``) a user is willing to wait for a single Rest call,
``3*200=600seconds``. Depending on usage, these may need to be overriden by
the user in the cinder.conf. For example, if performance is a factor, then the
``interval`` should be decreased to check the job status more frequently, and
if multiple concurrent provisioning requests are issued then ``retries``
should be increased so calls will not timeout prematurely.

In the example below, the driver checks every 3 seconds for the status of the
job. It will continue checking for 150 retries before it times out.

Add the following lines to the VMAX backend in the cinder.conf:

.. code-block:: console

   [CONF_GROUP_ISCSI]
   volume_driver = cinder.volume.drivers.dell_emc.vmax.iscsi.VMAXISCSIDriver
   cinder_dell_emc_config_file = /etc/cinder/cinder_dell_emc_config_CONF_GROUP_ISCSI.xml
   volume_backend_name = ISCSI_backend
   interval = 3
   retries = 200


QoS (Quality of Service) support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Quality of service (QOS) has traditionally been associated with network
bandwidth usage. Network administrators set limitations on certain networks
in terms of bandwidth usage for clients. This enables them to provide a
tiered level of service based on cost. The Nova/cinder QOS offer similar
functionality based on volume type setting limits on host storage bandwidth
per service offering. Each volume type is tied to specific QoS attributes
some of which are unique to each storage vendor. In the hypervisor, the QoS
limits the following

- Limit by throughput - Total bytes/sec, read bytes/sec, write bytes/sec
- Limit by IOPS - Total IOPS/sec, read IOPS/sec, write IOPS/sec

QoS enforcement in cinder is done either at the hypervisor (front end),
the storage subsystem (back end), or both. This document focuses on QoS
limits that are enforced by either the VMAX backend or the hypervisor
front end interchangeably or just back end (Vendor Specific). The VMAX driver
offers support for Total bytes/sec limit in throughput and Total IOPS/sec
limit of IOPS.

The VMAX driver supports the following attributes that are front end/back end
agnostic

- total_iops_sec - Maximum IOPs (in I/Os per second). Valid values range from
  100 IO/Sec to 100,000 IO/sec.
- total_bytes_sec - Maximum bandwidth (throughput) in bytes per second. Valid
  values range from 1048576bytes (1MB) to 104857600000bytes (100, 000MB)

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
                                    SILVER

#. Associate QoS specs with specified volume type:

   .. code-block:: console

      $ openstack volume qos associate SILVER VOLUME_TYPE

#. Create volume with the volume type indicated above:

   .. code-block:: console

      $ openstack volume create --size 1 --type VOLUME_TYPE TEST_VOLUME

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
                                    SILVER

#. Associate QoS specifications with specified volume type:

   .. code-block:: console

      $ openstack volume qos associate SILVER VOLUME_TYPE

#. Create volume with the volume type indicated above:

   .. code-block:: console

      $ openstack volume create --size 1 --type VOLUME_TYPE TEST_VOLUME

#. Attach the volume created in step 3 to an instance

   .. code-block:: console

      $ openstack server add volume TEST_VOLUME TEST_INSTANCE

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
i.e. instance-00000005. We then run the following command using the
``OS-EXT-SRV-ATTR:instance_name`` retrieved above.

.. code-block:: console

   $ virsh dumpxml instance-00000005 | grep -1 "total_bytes_sec\|total_iops_sec"

The outcome is shown below

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
                                    SILVER

#. Associate QoS specifications with specified volume type:

   .. code-block:: console

      $ openstack volume qos associate SILVER VOLUME_TYPE

#. Create volume with the volume type indicated above:

   .. code-block:: console

      $ openstack volume create --size 1 --type VOLUME_TYPE TEST_VOLUME

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
                                    SILVER

#. Associate QoS specifications with specified volume type:

   .. code-block:: console

      $ openstack volume qos associate SILVER VOLUME_TYPE


#. Create volume with the volume type indicated above:

   .. code-block:: console

      $ openstack volume create --size 1 --type VOLUME_TYPE TEST_VOLUME

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

   # apt-get install open-iscsi           #ensure iSCSI is installed
   # apt-get install multipath-tools      #multipath modules
   # apt-get install sysfsutils sg3-utils #file system utilities
   # apt-get install scsitools            #SCSI tools

On openSUSE and SUSE Linux Enterprise Server:

.. code-block:: console

   # zipper install open-iscsi           #ensure iSCSI is installed
   # zipper install multipath-tools      #multipath modules
   # zipper install sysfsutils sg3-utils #file system utilities
   # zipper install scsitools            #SCSI tools

On Red Hat Enterprise Linux and CentOS:

.. code-block:: console

   # yum install iscsi-initiator-utils   #ensure iSCSI is installed
   # yum install device-mapper-multipath #multipath modules
   # yum install sysfsutils sg3-utils    #file system utilities
   # yum install scsitools               #SCSI tools


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
:file:`/etc/nova/nova.conf`:

.. code-block:: ini

   iscsi_use_multipath = True

On cinder controller node, set the multipath flag to true in
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

      $ multipath -ll
      mpath102 (360000970000196700531533030383039) dm-3 EMC,SYMMETRIX
      size=3G features='1 queue_if_no_path' hwhandler='0' wp=rw
      '-+- policy='round-robin 0' prio=1 status=active
      33:0:0:1 sdb 8:16 active ready running
      '- 34:0:0:1 sdc 8:32 active ready running

#. Use the ``lsblk`` command to see the multipath device:

   .. code-block:: console

      $ lsblk
      NAME                                       MAJ:MIN RM   SIZE RO TYPE  MOUNTPOINT
      sdb                                          8:0    0     3G  0 disk
      ..360000970000196700531533030383039 (dm-6) 252:6    0     3G  0 mpath
      sdc                                          8:16   0     3G  0 disk
      ..360000970000196700531533030383039 (dm-6) 252:6    0     3G  0 mpath
      vda


Workload Planner (WLP)
~~~~~~~~~~~~~~~~~~~~~~

VMAX Hybrid allows you to manage application storage by using Service Level
(SL) using policy based automation. The VMAX Hybrid comes with
up to 6 SL policies defined. Each has a
set of workload characteristics that determine the drive types and mixes
which will be used for the SL. All storage in the VMAX Array is virtually
provisioned, and all of the pools are created in containers called Storage
Resource Pools (SRP). Typically there is only one SRP, however there can be
more. Therefore, it is the same pool we will provision to but we can provide
different SLO/Workload combinations.

The SL capacity is retrieved by interfacing with Unisphere Workload Planner
(WLP). If you do not set up this relationship then the capacity retrieved is
that of the entire SRP. This can cause issues as it can never be an accurate
representation of what storage is available for any given SL and Workload
combination.

Enabling WLP on Unisphere
-------------------------

#. To enable WLP on Unisphere, click on the
   :menuselection:`array-->Performance-->Settings`.
#. Set both the :guilabel:`Real Time` and the :guilabel:`Root Cause Analysis`.
#. Click :guilabel:`Register`.

.. note::

   This should be set up ahead of time (allowing for several hours of data
   collection), so that the Unisphere for VMAX Performance Analyzer can
   collect rated metrics for each of the supported element types.


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

   This feature is only applicable for All Flash arrays, 250F, 450F or 850F.

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


Use case 2 - Compression disabled create, delete snapshot and delete volume
---------------------------------------------------------------------------

#. Repeat steps 1-5 of Use case 1.
#. Create a snapshot. The volume should now exist in
   ``OS-<srp>-<servicelevel>-<workload>-CD-SG``.
#. Delete the snapshot. The volume should be removed from
   ``OS-<srp>-<servicelevel>-<workload>-CD-SG``.
#. Delete the volume. If this volume is the last volume in
   ``OS-<srp>-<servicelevel>-<workload>-CD-SG``, it should also be deleted.

Use case 3 - Retype from compression disabled to compression enabled
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

#. Configure a synchronous SRDF group between the chosen source and target
   arrays for the VMAX cinder driver to use. The source array must correspond
   with the ``<Array>`` entry in the VMAX XML file.
#. Select both the director and the ports for the SRDF emulation to use on
   both sides. Bear in mind that network topology is important when choosing
   director endpoints. Currently, the only supported mode is `Synchronous`.

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
      server), or enter the details to the XML file of a second Unisphere
      server, which is locally connected to the target array (for example, the
      embedded management Unisphere server of the target array), and restart
      the cinder volume service.

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
      cinder_dell_emc_config_file = /etc/cinder/cinder_dell_emc_config_VMAX_FC_REPLICATION.xml
      volume_backend_name = VMAX_FC_REPLICATION
      replication_device = target_device_id:000197811111, remote_port_group:os-failover-pg, remote_pool:SRP_1, rdf_group_label: 28_11_07, allow_extend:False

   * ``target_device_id`` is a unique VMAX array serial number of the target
     array. For full failover functionality, the source and target VMAX arrays
     must be discovered and managed by the same U4V server.

   * ``remote_port_group`` is the name of a VMAX port group that has been
     pre-configured to expose volumes managed by this backend in the event
     of a failover. Make sure that this portgroup contains either all FC or
     all iSCSI port groups (for a given back end), as appropriate for the
     configured driver (iSCSI or FC).
   * ``remote_pool`` is the unique pool name for the given target array.
   * ``rdf_group_label`` is the name of a VMAX SRDF group (Synchronous) that
     has been pre-configured between the source and target arrays.
   * ``allow_extend`` is a flag for allowing the extension of replicated volumes.
     To extend a volume in an SRDF relationship, this relationship must first be
     broken, both the source and target volumes are then independently extended,
     and then the replication relationship is re-established. If not explicitly
     set, this flag defaults to ``False``.

     .. note::
        As the SRDF link must be severed, due caution should be exercised when
        performing this operation. If absolutely necessary, only one source and
        target pair should be extended at a time.
        In Queens, the underlying VMAX architecture will support extending
        source and target volumes without having to sever links.

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

      $ openstack volume type set --property replication_enabled = "<is> True" \
                            VMAX_FC_REPLICATION


Volume replication interoperability with other features
-------------------------------------------------------

Most features are supported, except for the following:

* There is no OpenStack Generic Volume Group support for replication-enabled
  VMAX volumes.

* Storage-assisted retype operations on replication-enabled VMAX volumes
  (moving from a non-replicated type to a replicated-type and vice-versa.
  Moving to another service level/workload combination, for example) are
  not supported.

* The image volume cache functionality is supported (enabled by setting
  ``image_volume_cache_enabled = True``), but one of two actions must be taken
  when creating the cached volume:

  * The first boot volume created on a backend (which will trigger the
    cached volume to be created) should be the smallest necessary size.
    For example, if the minimum size disk to hold an image is 5GB, create
    the first boot volume as 5GB.
  * Alternatively, ensure that the ``allow_extend`` option in the
    ``replication_device parameter`` is set to ``True``.

  This is because the initial boot volume is created at the minimum required
  size for the requested image, and then extended to the user specified size.


Failover host
-------------

In the event of a disaster, or where there is required downtime, upgrade
of the primary array for example, the administrator can issue the failover
host command to failover to the configured target:

.. code-block:: console

   $ cinder failover-host cinder_host@VMAX_FC_REPLICATION#Diamond+SRP_1+000192800111

If the primary array becomes available again, you can initiate a failback
using the same command and specifying ``--backend_id default``:

.. code-block:: console

   $ cinder failover-host \
     cinder_host@VMAX_FC_REPLICATION#Diamond+SRP_1+000192800111 \
     --backend_id default


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
   (please above ``Setup VMAX Drivers`` for details).

   .. code-block:: console

      $ cinder retype --migration-policy on-demand <volume> <volume-type>


Generic volume group support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Generic volume group operations are performed through the CLI using API
version 3.1x of the cinder API. Generic volume groups are multi-purpose
groups which can be used for various features. The only feature supported
currently by the VMAX plugin is the ability to take group snapshots which
are consistent based on the group specs. Generic volume groups are a
replacement for the consistency groups.

Consistent group snapshot
-------------------------

For creating a consistent group snapshot, a group-spec, having the key
``consistent_group_snapshot_enabled`` set to ``<is> True``, should be set
on the group. Similarly the same key should be set on any volume type which
is specified while creating the group. The VMAX plugin doesn't support
creating/managing a group which doesn't have this group-spec set. If this key
is not set on the group-spec then the generic volume group will be
created/managed by cinder (not the VMAX plugin).

.. note::

   The consistent group snapshot should not be confused with the VMAX
   consistency which primarily applies to SRDF.

.. note::

   For creating consistent group snapshots, no changes are required to be
   done to the ``/etc/cinder/policy.json``.

Storage Group Names
-------------------

Storage groups are created on the VMAX as a result of creation of generic
volume groups. These storage groups follow a different naming convention
and are of the following format depending upon whether the groups have a
name.

.. code-block:: text

   TruncatedGroupName_GroupUUID or GroupUUID

Operations
----------

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

   cinder --os-volume-api-version 3.11 group-type-key GROUP_TYPE set consistent_group_snapshot_enabled= "<is> True"

- List group types and group specs:

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-specs-list

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

- Delete a group

.. code-block:: console

   cinder --os-volume-api-version 3.13 group-delete --delete-volumes GROUP


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
  ephemeral disk.  For VMAX volume-backed live migration on shared storage
  is required.

The VMAX driver supports shared storage-based live migration.

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


Libvirt configuration
---------------------

Make the following updates on all nodes, controller and compute nodes, that
are involved in live migration. Update the libvirt configurations. Please
refer to following link for further information:
http://libvirt.org/remote.html

#. Update the libvirt configurations. Modify the ``/etc/libvirt/libvirtd.conf``
   file

   .. code-block:: console

      before : #listen_tls = 0
      after : listen_tls = 0

      before : #listen_tcp = 1
      after : listen_tcp = 1
      add: auth_tcp = "none"

#. Modify the /etc/libvirt/qemu.conf file:

   .. code-block:: console

      before : #dynamic_ownership = 1
      after : dynamic_ownership = 0
      before : #security_driver = "selinux"
      after : security_driver = "none"
      before : #user = "root"
      after : user = "root"
      before : #group = "root"
      after : group = "root"

#. Modify the /etc/default/libvirtd file:

   .. code-block:: console

      before: libvirtd_opts=" -d"
      after: libvirtd_opts=" -d -l"

#. Restart libvirt. After you run the command below, ensure that libvirt is
   successfully restarted:

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
   https://help.ubuntu.com/community/SettingUpNFSHowTo

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
