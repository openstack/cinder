==================================
Dell EMC VMAX iSCSI and FC drivers
==================================

The Dell EMC VMAX drivers, ``VMAXISCSIDriver`` and ``VMAXFCDriver``, support
the use of Dell EMC VMAX storage arrays with Block Storage. They both provide
equivalent functions and differ only in support for their respective host
attachment methods.

The drivers perform volume operations by communicating with the back-end VMAX
storage. It uses a CIM client in Python called ``PyWBEM`` to perform CIM
operations over HTTP.

The EMC CIM Object Manager (ECOM) is packaged with the EMC SMI-S provider. It
is a CIM server that enables CIM clients to perform CIM operations over HTTP by
using SMI-S in the back end for VMAX storage operations.

The Dell EMC SMI-S Provider supports the SNIA Storage Management Initiative
(SMI), an ANSI standard for storage management. It supports the VMAX storage
system.

System requirements
~~~~~~~~~~~~~~~~~~~

The Cinder driver supports the VMAX-3 series.

For VMAX-3 series, Solutions Enabler 8.3.0.11 or later is required. This
is SSL only. Refer to section below ``SSL support``.

When installing Solutions Enabler, make sure you explicitly add the SMI-S
component.

You can download Solutions Enabler from the Dell EMC's support web site
(login is required). See the ``Solutions Enabler 8.3.0 Installation and
Configuration Guide`` at ``support.emc.com``.

Ensure that there is only one SMI-S (ECOM) server active on the same VMAX
array.


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
-  Create and delete consistency group
-  Create and delete consistency group snapshot
-  Modify consistency group (add and remove volumes)
-  Create consistency group from source
-  Create and delete generic volume group
-  Create and delete generice volume group snapshot
-  Modify generic volume group (add and remove volumes)
-  Create generic volume group from source

VMAX drivers also support the following features:

-  Dynamic masking view creation
-  Dynamic determination of the target iSCSI IP address
-  iSCSI multipath support
-  Oversubscription
-  Live Migration
-  Attach and detach snapshots
-  Volume replication

VMAX All Flash and Hybrid:

-  Service Level support
-  SnapVX support
-  All Flash support
-  Compression support

.. note::

   VMAX All Flash array with Solutions Enabler 8.3.0.11 or later have
   compression enabled by default when associated with Diamond Service Level.
   This means volumes added to any newly created storage groups will be
   compressed.

Setup VMAX drivers
~~~~~~~~~~~~~~~~~~

.. table:: **Pywbem Versions**

 +------------+-----------------------------------+
 |  Pywbem    | Ubuntu14.04(LTS),Ubuntu16.04(LTS),|
 |  Version   | Red Hat Enterprise Linux, CentOS  |
 |            | and Fedora                        |
 +============+=================+=================+
 |            | Python2         | Python3         |
 +            +-------+---------+-------+---------+
 |            | pip   | Native  | pip   | Native  |
 +------------+-------+---------+-------+---------+
 |   0.9.0    |  No   |   N/A   |  Yes  |   N/A   |
 +------------+-------+---------+-------+---------+
 |   0.8.4    |  No   |   N/A   |  Yes  |   N/A   |
 +------------+-------+---------+-------+---------+
 |   0.7.0    |  No   |   Yes   |  No   |   Yes   |
 +------------+-------+---------+-------+---------+

.. note::

   On Python2, use the updated distro version, for example:

   .. code-block:: console

      # apt-get install python-pywbem

.. note::

   On Python3, use the official pywbem version (V0.9.0 or v0.8.4).

#. Install the ``python-pywbem`` package for your distribution.

   -  On Ubuntu:

      .. code-block:: console

         # apt-get install python-pywbem

   -  On openSUSE:

      .. code-block:: console

         # zypper install python-pywbem

   -  On Red Hat Enterprise Linux, CentOS, and Fedora:

      .. code-block:: console

         # yum install pywbem

   .. note::

      A potential issue can exist with the ``python-pywbem`` dependency package,
      especially M2crypto. To troubleshot and resolve these types of issues,
      follow these steps.

      -  On Ubuntu:

         .. code-block:: console

            # apt-get remove --purge -y python-m2crypto
            # pip uninstall pywbem
            # apt-get install python-pywbem

      -  On openSUSE:

         .. code-block:: console

            # zypper remove --clean-deps python-m2crypto
            # pip uninstall pywbem
            # zypper install python-pywbem

      -  On Red Hat Enterprise Linux, CentOS, and Fedora:

         .. code-block:: console

            # yum remove python-m2crypto
            # sudo pip uninstall pywbem
            # yum install pywbem

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
   Make sure you install the SMIS component. A [Y]es response installs the
   ``SMISPROVIDER`` component.

   .. code-block:: console

      Install EMC Solutions Enabler SMIS Component ? [N]:Y

   You can install Solutions Enabler on a non-OpenStack host. Supported
   platforms include different flavors of Windows, Red Hat, and SUSE Linux.
   Solutions Enabler can be installed on a physical server or a VM hosted by
   an ESX server. Note that the supported hypervisor for a VM running
   Solutions Enabler is ESX only. See the ``Solutions Enabler 8.3.0
   Installation and Configuration Guide`` on ``support.emc.com`` for more
   details.

   .. note::

      You must discover storage arrays on the ECOM before you can use
      the VMAX drivers. Follow instructions in ``Solutions Enabler 8.3.0
      Installation and Configuration Guide`` on ``support.emc.com`` for more
      details.

   The ECOM server is usually installed at ``/opt/emc/ECIM/ECOM/bin`` on Linux
   and ``C:\Program Files\EMC\ECIM\ECOM\bin`` on Windows. After you install and
   configure the ECOM, go to that directory and type ``TestSmiProvider.exe``
   for windows and ``./TestSmiProvider`` for linux

   Use ``addsys`` in ``TestSmiProvider`` to add an array. Use ``dv`` and examine
   the output after the array is added. In advance of ``TestSmiProvider``,
   arrays need to be discovered on the Solutions Enabler by using the
   :command:`symcfg discover` command. Make sure that the arrays are recognized by the
   SMI-S server before using the EMC VMAX drivers.

#. Configure Block Storage

   Add the following entries to ``/etc/cinder/cinder.conf``:

   .. code-block:: ini

      enabled_backends = CONF_GROUP_ISCSI, CONF_GROUP_FC

      [CONF_GROUP_ISCSI]
      volume_driver = cinder.volume.drivers.dell_emc.vmax.iscsi.VMAXISCSIDriver
      cinder_emc_config_file = /etc/cinder/cinder_emc_config_CONF_GROUP_ISCSI.xml
      volume_backend_name = ISCSI_backend

      [CONF_GROUP_FC]
      volume_driver = cinder.volume.drivers.dell_emc.vmax.fc.EMCVMAXFCDriver
      cinder_emc_config_file = /etc/cinder/cinder_emc_config_CONF_GROUP_FC.xml
      volume_backend_name = FC_backend

   In this example, two back-end configuration groups are enabled:
   ``CONF_GROUP_ISCSI`` and ``CONF_GROUP_FC``. Each configuration group has a
   section describing unique parameters for connections, drivers, the
   ``volume_backend_name``, and the name of the EMC-specific configuration file
   containing additional settings. Note that the file name is in the format
   ``/etc/cinder/cinder_emc_config_[confGroup].xml``.

   Once the ``cinder.conf`` and EMC-specific configuration files have been
   created, :command:`openstack` commands need to be issued in order to create and
   associate OpenStack volume types with the declared ``volume_backend_names``:

   .. code-block:: console

      $ openstack volume type create VMAX_ISCSI
      $ openstack volume type set --property volume_backend_name=ISCSI_backend VMAX_ISCSI
      $ openstack volume type create VMAX_FC
      $ openstack volume type set --property volume_backend_name=FC_backend VMAX_FC

   By issuing these commands, the Block Storage volume type ``VMAX_ISCSI`` is
   associated with the ``ISCSI_backend``, and the type ``VMAX_FC`` is
   associated with the ``FC_backend``.


   Create the ``/etc/cinder/cinder_emc_config_CONF_GROUP_ISCSI.xml`` file.
   You do not need to restart the service for this change.

   Add the following lines to the XML file:

   VMAX All Flash and Hybrid
     .. code-block:: xml

       <?xml version="1.0" encoding="UTF-8" ?>
       <EMC>
         <EcomServerIp>1.1.1.1</EcomServerIp>
         <EcomServerPort>00</EcomServerPort>
         <EcomUserName>user1</EcomUserName>
         <EcomPassword>password1</EcomPassword>
         <PortGroups>
           <PortGroup>OS-PORTGROUP1-PG</PortGroup>
           <PortGroup>OS-PORTGROUP2-PG</PortGroup>
         </PortGroups>
         <Array>111111111111</Array>
         <Pool>SRP_1</Pool>
         <ServiceLevel>Diamond</ServiceLevel>
         <Workload>OLTP</Workload>
       </EMC>

   Where:

.. note::

   VMAX Hybrid supports Optimized, Diamond, Platinum, Gold, Silver, Bronze, and
   NONE service levels. VMAX All Flash supports Diamond and NONE. Both
   support DSS_REP, DSS, OLTP_REP, OLTP, and NONE workloads.

``EcomServerIp``
    IP address of the ECOM server which is packaged with SMI-S.

``EcomServerPort``
    Port number of the ECOM server which is packaged with SMI-S.

``EcomUserName`` and ``EcomPassword``
    Credentials for the ECOM server.

``PortGroups``
    Supplies the names of VMAX port groups that have been pre-configured to
    expose volumes managed by this backend. Each supplied port group should
    have sufficient number and distribution of ports (across directors and
    switches) as to ensure adequate bandwidth and failure protection for the
    volume connections. PortGroups can contain one or more port groups of
    either iSCSI or FC ports. When a dynamic masking view is created by the
    VMAX driver, the port group is chosen randomly from the PortGroup list, to
    evenly distribute load across the set of groups provided. Make sure that
    the PortGroups set contains either all FC or all iSCSI port groups (for a
    given back end), as appropriate for the configured driver (iSCSI or FC).

``Array``
    Unique VMAX array serial number.

``Pool``
    Unique pool name within a given array. For back ends not using FAST
    automated tiering, the pool is a single pool that has been created by the
    administrator. For back ends exposing FAST policy automated tiering, the
    pool is the bind pool to be used with the FAST policy.

``ServiceLevel``
    VMAX All Flash and Hybrid only. The Service Level manages the underlying
    storage to provide expected performance. Omitting the ``ServiceLevel``
    tag means that non FAST storage groups will be created instead
    (storage groups not associated with any service level).

``Workload``
    VMAX All Flash and Hybrid only. When a workload type is added, the latency
    range is reduced due to the added information. Omitting the ``Workload``
    tag means the latency range will be the widest for its SLO type.

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

VMAX All Flash and Hybrid

.. code-block:: text

   OS-[shortHostName]-[SRP]-[SLO]-[workload]-[protocol]-MV

Initiator group names
---------------------

For each host that is attached to VMAX volumes using the drivers, an initiator
group is created or re-used (per attachment type). All initiators of the
appropriate type known for that host are included in the group. At each new
attach volume operation, the VMAX driver retrieves the initiators (either WWNNs
or IQNs) from OpenStack and adds or updates the contents of the Initiator Group
as required. Names are of the following format. ``[protocol]`` is either ``I``
for volumes attached over iSCSI or ``F`` for volumes attached over Fiber
Channel.

.. code-block:: text

   OS-[shortHostName]-[protocol]-IG

.. note::

   Hosts attaching to OpenStack managed VMAX storage cannot also attach to
   storage on the same VMAX that are not managed by OpenStack.

FA port groups
--------------

VMAX array FA ports to be used in a new masking view are chosen from the list
provided in the EMC configuration file.

Storage group names
-------------------

As volumes are attached to a host, they are either added to an existing storage
group (if it exists) or a new storage group is created and the volume is then
added. Storage groups contain volumes created from a pool (either single-pool
or FAST-controlled), attached to a single host, over a single connection type
(iSCSI or FC). ``[protocol]`` is either ``I`` for volumes attached over iSCSI
or ``F`` for volumes attached over Fiber Channel.

VMAX All Flash and Hybrid

.. code-block:: text

   OS-[shortHostName]-[SRP]-[SLO]-[Workload]-[protocol]-SG


Interval and Retries
--------------------

By default, ``Interval`` and ``Retries`` are ``10`` seconds and ``60``
retries respectively. These determine how long (``Interval``) and how many
times (``Retries``) a user is willing to wait for a single SMIS call,
``10*60=300seconds``. Depending on usage, these may need to be overriden by
the user in the XML file.  For example, if performance is a factor, then the
``Interval`` should be decreased to check the job status more frequently,
and if multiple concurrent provisioning requests are issued then ``Retries``
should be increased so calls will not timeout prematurely.

In the example below, the driver checks every 5 seconds for the status of the
job. It will continue checking for 120 retries before it times out.

Add the following lines to the XML file:

   VMAX All Flash and Hybrid

     .. code-block:: xml

       <?xml version="1.0" encoding="UTF-8" ?>
       <EMC>
         <EcomServerIp>1.1.1.1</EcomServerIp>
         <EcomServerPort>00</EcomServerPort>
         <EcomUserName>user1</EcomUserName>
         <EcomPassword>password1</EcomPassword>
         <PortGroups>
           <PortGroup>OS-PORTGROUP1-PG</PortGroup>
           <PortGroup>OS-PORTGROUP2-PG</PortGroup>
         </PortGroups>
         <Array>111111111111</Array>
         <Pool>SRP_1</Pool>
         <Interval>5</Interval>
         <Retries>120</Retries>
       </EMC>

SSL support
~~~~~~~~~~~

.. note::
   The ECOM component in Solutions Enabler enforces SSL in 8.3.0.1 or later.
   By default, this port is 5989.

#. Get the CA certificate of the ECOM server. This pulls the CA cert file and
   saves it as .pem file. The ECOM server IP address or hostname is ``my_ecom_host``.
   The sample name of the .pem file is ``ca_cert.pem``:

   .. code-block:: console

      # openssl s_client -showcerts -connect my_ecom_host:5989 </dev/null 2>/dev/null|openssl x509 -outform PEM >ca_cert.pem

#. Copy the pem file to the system certificate directory:

   .. code-block:: console

      # cp ca_cert.pem /usr/share/ca-certificates/ca_cert.crt

#. Update CA certificate database with the following commands:

   .. code-block:: console

      # sudo dpkg-reconfigure ca-certificates

   .. note::
      Check that the new ``ca_cert.crt`` will activate by selecting
      :guilabel:`ask` on the dialog. If it is not enabled for activation, use the
      down and up keys to select, and the space key to enable or disable.

   .. code-block:: console

      # sudo update-ca-certificates

#. Update :file:`/etc/cinder/cinder.conf` to reflect SSL functionality by
   adding the following to the back end block. ``my_location`` is the location
   of the .pem file generated in step one:

   .. code-block:: ini

      driver_ssl_cert_verify = False
      driver_use_ssl = True

   If you skip steps two and three, you must add the location of you .pem file.

   .. code-block:: ini

      driver_ssl_cert_verify = False
      driver_use_ssl = True
      driver_ssl_cert_path = /my_location/ca_cert.pem

#. Update EcomServerIp to ECOM host name and EcomServerPort to secure port
   (5989 by default) in :file:`/etc/cinder/cinder_emc_config_<conf_group>.xml`.


Oversubscription support
~~~~~~~~~~~~~~~~~~~~~~~~

Oversubscription support requires the ``/etc/cinder/cinder.conf`` to be
updated with two additional tags ``max_over_subscription_ratio`` and
``reserved_percentage``. In the sample below, the value of 2.0 for
``max_over_subscription_ratio`` means that the pools in oversubscribed by a
factor of 2, or 200% oversubscribed. The ``reserved_percentage`` is the high
water mark where by the physical remaining space cannot be exceeded.
For example, if there is only 4% of physical space left and the reserve
percentage is 5, the free space will equate to zero. This is a safety
mechanism to prevent a scenario where a provisioning request fails due to
insufficient raw space.

The parameter ``max_over_subscription_ratio`` and ``reserved_percentage`` are
optional.

To set these parameter go to the configuration group of the volume type in
:file:`/etc/cinder/cinder.conf`.

.. code-block:: ini

    [VMAX_ISCSI_SILVER]
    cinder_emc_config_file = /etc/cinder/cinder_emc_config_VMAX_ISCSI_SILVER.xml
    volume_driver = cinder.volume.drivers.dell_emc.vmax.iscsi.VMAXISCSIDriver
    volume_backend_name = VMAX_ISCSI_SILVER
    max_over_subscription_ratio = 2.0
    reserved_percentage = 10

For the second iteration of over subscription, take into account the
EMCMaxSubscriptionPercent property on the pool. This value is the highest
that a pool can be oversubscribed.

Scenario 1
----------

``EMCMaxSubscriptionPercent`` is 200 and the user defined
``max_over_subscription_ratio`` is 2.5, the latter is ignored.
Oversubscription is 200%.

Scenario 2
----------

``EMCMaxSubscriptionPercent`` is 200 and the user defined
``max_over_subscription_ratio`` is 1.5, 1.5 equates to 150% and is less than
the value set on the pool. Oversubscription is 150%.

Scenario 3
----------

``EMCMaxSubscriptionPercent`` is 0. This means there is no upper limit on the
pool. The user defined ``max_over_subscription_ratio`` is 1.5.
Oversubscription is 150%.

Scenario 4
----------

``EMCMaxSubscriptionPercent`` is 0. ``max_over_subscription_ratio`` is not
set by the user. We recommend to default to upper limit, this is 150%.

.. note::
   If FAST is set and multiple pools are associated with a FAST policy,
   then the same rules apply. The difference is, the TotalManagedSpace and
   EMCSubscribedCapacity for each pool associated with the FAST policy are
   aggregated.

Scenario 5
----------

``EMCMaxSubscriptionPercent`` is 200 on one pool. It is 300 on another pool.
The user defined ``max_over_subscription_ratio`` is 2.5. Oversubscription is
200% on the first pool and 250% on the other.

QoS (Quality of Service) support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Quality of service(QoS) has traditionally been associated with network
bandwidth usage. Network administrators set limitations on certain networks
in terms of bandwidth usage for clients. This enables them to provide a
tiered level of service based on cost. The cinder QoS offers similar
functionality based on volume type setting limits on host storage bandwidth
per service offering. Each volume type is tied to specific QoS attributes
that are unique to each storage vendor. The VMAX plugin offers limits via
the following attributes:

- By I/O limit per second (IOPS)
- By limiting throughput per second (MB/S)
- Dynamic distribution
- The VMAX offers modification of QoS at the Storage Group level

USE CASE 1 - Default values
---------------------------

Prerequisites - VMAX

- Host I/O Limit (MB/Sec) -     No Limit
- Host I/O Limit (IO/Sec) -     No Limit
- Set Dynamic Distribution -    N/A

.. table:: **Prerequisites - Block Storage (cinder) back end (storage group)**

 +-------------------+--------+
 |  Key              | Value  |
 +===================+========+
 |  maxIOPS          | 4000   |
 +-------------------+--------+
 |  maxMBPS          | 4000   |
 +-------------------+--------+
 |  DistributionType | Always |
 +-------------------+--------+

#. Create QoS Specs with the prerequisite values above:

   .. code-block:: console

      $ openstack volume qos create --property maxIOPS=4000 maxMBPS=4000 DistributionType=Always SILVER

#. Associate QoS specs with specified volume type:

   .. code-block:: console

      $ openstack volume qos associate SILVER VOLUME_TYPE

#. Create volume with the volume type indicated above:

   .. code-block:: console

      $ openstack volume create --size 1 --type VOLUME_TYPE TEST_VOLUME

**Outcome - VMAX (storage group)**

- Host I/O Limit (MB/Sec) -     4000
- Host I/O Limit (IO/Sec) -     4000
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

 +-------------------+--------+
 |  Key              | Value  |
 +===================+========+
 |  maxIOPS          | 4000   |
 +-------------------+--------+
 |  maxMBPS          | 4000   |
 +-------------------+--------+
 |  DistributionType | Always |
 +-------------------+--------+

#. Create QoS specifications with the prerequisite values above:

   .. code-block:: console

      $ openstack volume qos create --property maxIOPS=4000 maxMBPS=4000 DistributionType=Always SILVER

#. Associate QoS specifications with specified volume type:

   .. code-block:: console

      $ openstack volume qos associate SILVER VOLUME_TYPE

#. Create volume with the volume type indicated above:

   .. code-block:: console

      $ openstack volume create --size 1 --type VOLUME_TYPE TEST_VOLUME

**Outcome - VMAX (storage group)**

- Host I/O Limit (MB/Sec) -     4000
- Host I/O Limit (IO/Sec) -     4000
- Set Dynamic Distribution -    Always

**Outcome - Block Storage (cinder)**

Volume is created against volume type and QoS is enforced with the parameters
above.


USE CASE 3 - Preset limits
--------------------------

Prerequisites - VMAX

- Host I/O Limit (MB/Sec) -     No Limit
- Host I/O Limit (IO/Sec) -     No Limit
- Set Dynamic Distribution -    N/A

.. table:: **Prerequisites - Block Storage (cinder) back end (storage group)**

 +-------------------+--------+
 |  Key              | Value  |
 +===================+========+
 |  DistributionType | Always |
 +-------------------+--------+

#. Create QoS specifications with the prerequisite values above:

   .. code-block:: console

      $ openstack volume qos create --property DistributionType=Always SILVER

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

USE CASE 4 - Preset limits
--------------------------

Prerequisites - VMAX

- Host I/O Limit (MB/Sec) -     No Limit
- Host I/O Limit (IO/Sec) -     No Limit
- Set Dynamic Distribution -    N/A

.. table:: **Prerequisites - Block Storage (cinder) back end (storage group)**

 +-------------------+-----------+
 |  Key              | Value     |
 +===================+===========+
 |  DistributionType | OnFailure |
 +-------------------+-----------+

#. Create QoS specifications with the prerequisite values above:

   .. code-block:: console

      $ openstack volume qos create --property DistributionType=OnFailure SILVER

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

Consistency group support
~~~~~~~~~~~~~~~~~~~~~~~~~

Consistency Groups operations are performed through the CLI using v2 of
the cinder API.

:file:`/etc/cinder/policy.json` may need to be updated to enable new API calls
for Consistency groups.

.. note::
   Even though the terminology is 'Consistency Group' in OpenStack, a Storage
   Group is created on the VMAX, and should not be confused with a VMAX
   Consistency Group which is an SRDF feature. The Storage Group is not
   associated with any Service Level.

Operations
----------

* Create a Consistency Group:

  .. code-block:: console

     cinder --os-volume-api-version 2 consisgroup-create [--name <name>]
     [--description <description>] [--availability-zone <availability-zone>]
     <volume-types>

  .. code-block:: console

     $ cinder --os-volume-api-version 2 consisgroup-create --name bronzeCG2 volume_type_1

* List Consistency Groups:

  .. code-block:: console

     cinder consisgroup-list [--all-tenants [<0|1>]]

  .. code-block:: console

      $ cinder consisgroup-list

* Show a Consistency Group:

  .. code-block:: console

     cinder consisgroup-show <consistencygroup>

  .. code-block:: console

     $ cinder consisgroup-show 38a604b7-06eb-4202-8651-dbf2610a0827

* Update a consistency Group:

  .. code-block:: console

     cinder consisgroup-update [--name <name>] [--description <description>]
     [--add-volumes <uuid1,uuid2,......>] [--remove-volumes <uuid3,uuid4,......>]
     <consistencygroup>

  Change name:

  .. code-block:: console

     $ cinder consisgroup-update --name updated_name 38a604b7-06eb-4202-8651-dbf2610a0827

  Add volume(s) to a Consistency Group:

  .. code-block:: console

     $ cinder consisgroup-update --add-volumes af1ae89b-564b-4c7f-92d9-c54a2243a5fe 38a604b7-06eb-4202-8651-dbf2610a0827

  Delete volume(s) from a Consistency Group:

  .. code-block:: console

     $ cinder consisgroup-update --remove-volumes af1ae89b-564b-4c7f-92d9-c54a2243a5fe 38a604b7-06eb-4202-8651-dbf2610a0827

* Create a snapshot of a Consistency Group:

  .. code-block:: console

     cinder cgsnapshot-create [--name <name>] [--description <description>]
     <consistencygroup>

  .. code-block:: console

     $ cinder cgsnapshot-create 618d962d-2917-4cca-a3ee-9699373e6625

* Delete a snapshot of a Consistency Group:

  .. code-block:: console

     cinder cgsnapshot-delete <cgsnapshot> [<cgsnapshot> ...]

  .. code-block:: console

     $ cinder cgsnapshot-delete 618d962d-2917-4cca-a3ee-9699373e6625

* Delete a Consistency Group:

  .. code-block:: console

     cinder consisgroup-delete [--force] <consistencygroup> [<consistencygroup> ...]

  .. code-block:: console

     $ cinder consisgroup-delete --force 618d962d-2917-4cca-a3ee-9699373e6625

* Create a Consistency group from source:

  .. code-block:: console

     cinder consisgroup-create-from-src [--cgsnapshot <cgsnapshot>]
     [--source-cg <source-cg>] [--name <name>] [--description <description>]

  .. code-block:: console

     $ cinder consisgroup-create-from-src --source-cg 25dae184-1f25-412b-b8d7-9a25698fdb6d

  .. code-block:: console

     $ cinder consisgroup-create-from-src --cgsnapshot 618d962d-2917-4cca-a3ee-9699373e6625

* You can also create a volume in a consistency group in one step:

  .. code-block:: console

     $ openstack volume create [--consistency-group consistency-group>]
       [--description <description>]  [--type <volume-type>]
       [--availability-zone <availability-zone>]  [--size <size>] <name>

  .. code-block:: console

     $ openstack volume create --type volume_type_1 ----consistency-group \
       1de80c27-3b2f-47a6-91a7-e867cbe36462 --size 1 cgBronzeVol


Workload Planner (WLP)
~~~~~~~~~~~~~~~~~~~~~~

VMAX Hybrid allows you to manage application storage by using Service Level
Objectives (SLO) using policy based automation rather than the tiering in the
VMAX2. The VMAX Hybrid comes with up to 6 SLO policies defined. Each has a
set of workload characteristics that determine the drive types and mixes
which will be used for the SLO. All storage in the VMAX Array is virtually
provisioned, and all of the pools are created in containers called Storage
Resource Pools (SRP). Typically there is only one SRP, however there can be
more. Therefore, it is the same pool we will provision to but we can provide
different SLO/Workload combinations.

The SLO capacity is retrieved by interfacing with Unisphere Workload Planner
(WLP). If you do not set up this relationship then the capacity retrieved is
that of the entire SRP. This can cause issues as it can never be an accurate
representation of what storage is available for any given SLO and Workload
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

Using TestSmiProvider to add statistics access point
----------------------------------------------------

After enabling WLP you must then enable SMI-S to gain access to the WLP data:

#. Connect to the SMI-S Provider using TestSmiProvider.
#. Navigate to the :guilabel:`Active` menu.
#. Type ``reg`` and enter the noted responses to the questions:

   .. code-block:: console

      (EMCProvider:5989) ? reg
      Current list of statistics Access Points: ?
      Note: The current list will be empty if there are no existing Access Points.
      Add Statistics Access Point {y|n} [n]: y
      HostID [l2se0060.lss.emc.com]: ?
      Note: Enter the Unisphere for VMAX location using a fully qualified Host ID.
      Port [8443]: ?
      Note: The Port default is the Unisphere for VMAX default secure port. If the secure port
      is different for your Unisphere for VMAX setup, adjust this value accordingly.
      User [smc]: ?
      Note: Enter the Unisphere for VMAX username.
      Password [smc]: ?
      Note: Enter the Unisphere for VMAX password.

#. Type ``reg`` again to view the current list:

   .. code-block:: console

      (EMCProvider:5988) ? reg
      Current list of statistics Access Points:
      HostIDs:
      l2se0060.lss.emc.com
      PortNumbers:
      8443
      Users:
      smc
      Add Statistics Access Point {y|n} [n]: n


Attach and detach snapshots
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``Attach snapshot`` and ``Detach snapshot`` are used internally by
non-disruptive backup and backup snapshot. As of the Newton release,
it is possible to back up a volume, but not possible to directly back up
a snapshot. Volume back up functionality has been available ever since backups
were introduced into the Cinder service. The ability to back up a volume
directly is valuable because you can back up a volume in one step. Users can
take snapshots from the volumes as a way to protect their data. These snapshots
reside on the storage backend itself. Providing a way
to backup snapshots directly allows users to protect the snapshots
taken from the volumes on a backup device, separately from the storage
backend.

There are users who have taken many snapshots and would like a way to protect
these snapshots. The functionality to backup snapshots provides another layer
of data protection.

Please refer to `backup and restore volumes and
snapshots <https://docs.openstack.org/admin-guide/blockstorage-volume-backups.html>`
for more more information.

Enable attach and detach snapshot functionality
-----------------------------------------------

#. Ensure that the ``cinder-backup`` service is running.
#. The backup driver for the swift back end performs a volume backup to an
   object storage system. To enable the swift backup driver, include the
   following option in the ``cinder.conf`` file:

   .. code-block:: yaml

      backup_driver = cinder.backup.drivers.swift

#. In order to force the volume to run attach and detach on the snapshot
   and not the volume you need to put the following key-value pair in the
   ``[DEFAULT]`` section of the ``cinder.conf``:

   .. code-block:: console

      backup_use_same_host = True

.. note::

   You may need to increase the message queue timeout value which is 60 by
   default in the ``[DEFAULT]`` section of the ``cinder.conf``. This is
   necessary because the snapshot may take more than this time.

  .. code-block:: console

     rpc_response_timeout = 240

Use case 1 - Create a volume backup when the volume is in-use
-------------------------------------------------------------

#. Create a bootable volume and launch it so the volume status is in-use.
#. Create a backup of the volume, where ``VOLUME``
   is the volume name or volume ``ID``. This will initiate a snapshot attach
   and a snapshot detach on a temporary snapshot:

   .. code-block:: console

      openstack backup create --force VOLUME

#. For example:

   .. code-block:: console

      openstack backup create --force cba1ca83-b857-421a-87c3-df81eb9ea8ab

Use case 2 - Restore a backup of a volume
-----------------------------------------

#. Restore the backup from Use case 1, where ``BACKUP_ID`` is the identifier of
   the backup from Use case 1.

   .. code-block:: console

      openstack backup restore BACKUP_ID

#. For example:

   .. code-block:: console

      openstack backup restore ec7e17ec-ae3c-4495-9ee6-7f45c9a89572

Once complete, launch the back up as an instance, and it should be a
bootable volume.

Use case 3 - Create a backup of a snapshot
------------------------------------------

#. Create a volume.
#. Create a snapshot of the volume.
#. Create a backup of the snapshot, where ``VOLUME`` is the volume name or
   volume ID, ``SNAPSHOT_ID`` is the ID of the volume's snapshot. This will
   initiate a snapshot attach and a snapshot detach on the snapshot.

   .. code-block:: console

      openstack backup create [--snapshot SNAPSHOT_ID} VOLUME

#. For example:

   .. code-block:: console

      openstack backup create --snapshot 6ab440c2-80ef-4f16-ac37-2d9db938732c 9fedfc4a-5f25-4fa1-8d8d-d5bec91f72e0

Use case 4 - Restore backup of a snapshot
-----------------------------------------

#. Restore the backup where ``BACKUP_ID`` is the identifier of the backup from
   Use case 3.

   .. code-block:: console

      openstack backup restore BACKUP_ID

#. For example:

   .. code-block:: console

      openstack backup restore ec7e17ec-ae3c-4495-9ee6-7f45c9a89572


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
   ``OS-<shorthostname>-<srp>-<servicelevel>-<workload>-CD-SG``, and
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
      For full failover functionality, the source and target VMAX arrays must be
      discovered and managed by the same SMI-S/ECOM server, locally connected
      for example. This SMI-S/ ECOM server cannot be embedded - it can be
      installed on a physical server or a VM hosted by an ESX server only.

   .. note::
      With both arrays being managed by the one SMI-S server, it is the cloud
      storage administrators responsibility to account for a DR scenario where the
      management (SMI-S) server goes down as well as the primary array. In that
      event, the details and credentials of a back-up SMI-S server can be passed
      in to the XML file, and the VMAX cinder driver can be rebooted. It would be
      advisable to have the SMI-S server at a third location (separate from both
      arrays) if possible.

   .. note::
      If the source and target arrays are not managed by the same management
      server (that is, the target array is remotely connected to server), in the
      event of a full disaster scenario (for example, the primary array is
      completely lost and all connectivity to it is gone), the SMI-S server
      would no longer be able to contact the target array. In this scenario,
      the volumes would be automatically failed over to the target array, but
      administrator intervention would be required to either; configure the
      target (remote) array as local to the current SMI-S server, or enter
      the details to the XML file of a second SMI-S server, which is locally
      connected to the target array, and restart the cinder volume service.

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
      volume_driver = cinder.volume.drivers.emc.emc_vmax_FC.EMCVMAXFCDriver
      cinder_emc_config_file = /etc/cinder/cinder_emc_config_VMAX_FC_REPLICATION.xml
      volume_backend_name = VMAX_FC_REPLICATION
      replication_device = target_device_id:000197811111, remote_port_group:os-failover-pg, remote_pool:SRP_1, rdf_group_label: 28_11_07, allow_extend:False

   * ``target_device_id`` is a unique VMAX array serial number of the target
     array. For full failover functionality, the source and target VMAX arrays
     must be discovered and managed by the same SMI-S/ECOM server.
     That is, locally connected. Follow the instructions in the SMI-S release
     notes.

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
     and then the replication relationship is re-established. As the SRDF link
     must be severed, due caution should be exercised when performing this
     operation. If not explicitly set, this flag defaults to ``False``.

   .. note::
      Service Level and Workload: An attempt will be made to create a storage
      group on the target array with the same service level and workload combination
      as the primary. However, if this combination is unavailable on the target
      (for example, in a situation where the source array is a Hybrid, the target array
      is an All Flash, and an All Flash incompatible SLO like Bronze is
      configured), no SLO will be applied.

   .. note::
      The VMAX cinder drivers can support a single replication target per
      back-end, that is we do not support Concurrent SRDF or Cascaded SRDF.
      Ensure there is only a single ``.replication_device.`` entry per
      back-end stanza.

#. Create a ``replication-enabled`` volume type. Once the
   ``replication_device`` parameter has been entered in the VMAX
   backend entry in the ``cinder.conf``, a corresponding volume type
   needs to be created ``replication_enabled`` property set. See
   above ``Setup VMAX drivers`` for details.

   .. code-block:: console

      $ openstack volume type set --property replication_enabled = ``<is> True`` VMAX_FC_REPLICATION


Volume replication interoperability with other features
-------------------------------------------------------

Most features are supported, except for the following:

* There is no OpenStack Consistency Group or Generic Volume Group support
  for replication-enabled VMAX volumes.

* Storage-assisted retype operations on replication-enabled VMAX volumes
  (moving from a non-replicated type to a replicated-type and vice-versa.
  Moving to another SLO/workload combination, for example) are not supported.

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

#. Add the parameter ``multi_pool_support`` to the configuration group in the
   ``/etc/cinder/cinder.conf`` file and set it to ``True``.

   .. code-block:: console

      [CONF_GROUP_FC]
      volume_driver = cinder.volume.drivers.dell_emc.vmax.fc.EMCVMAXFCDriver
      cinder_emc_config_file = /etc/cinder/cinder_emc_config_CONF_GROUP_FC.xml
      volume_backend_name = FC_backend
      multi_pool_support = True

#. Configure a single backend per SRP for the ``VMAX`` (Only VMAX3 arrays).
   This is different from the regular configuration where one backend is
   configured per service level.

#. Create the ``/etc/cinder/cinder_emc_config_CONF_GROUP_FC.xml`` and add
   the following lines to the XML for VMAX All Flash and Hybrid.

   .. code-block:: console

      <?xml version = "1.0" encoding = "UTF-8" ?>
      <EMC>
         <EcomServerIp>1.1.1.1</EcomServerIp>
         <EcomServerPort>00</EcomServerPort>
         <EcomUserName>user1</EcomUserName>
         <EcomPassword>password1</EcomPassword>
         <PortGroups>
            <PortGroup>OS-PORTGROUP1-PG</PortGroup>
            <PortGroup>OS-PORTGROUP2-PG</PortGroup>
         </PortGroups>
         <Array>111111111111</Array>
         <Pool>SRP_1</Pool>
      </EMC>

   .. note::
      There is no need to specify the Service Level and Workload in the XML
      file. A single XML file corresponding to the backend is sufficient
      instead of creating one each for the desired Service Level and Workload
      combination.

#. Once the backend is configured in the ``cinder.conf`` file and the VMAX
   specific configuration XML created, restart the cinder volume service for
   the changes to take place.

#. Run the command ``cinder get-pools --detail`` to query for the pool
   information. This should list all the available Service Level and Workload
   combinations available for the SRP as pools belonging to the same backend.

#. Use the following examples of OpenStack commands to create various volume
   types. The below example demonstrates creating a volume type for Diamond
   Service Level and OLTP workload.

   .. code-block:: console

      $ openstack volume type create VMAX_FC_DIAMOND_OLTP
      $ openstack volume type set --property volume_backend_name=FC_backend VMAX_FC_DIAMOND_OLTP
      $ openstack volume type set --property pool_name=Diamond+OLTP+SRP_1+111111111111

   .. note::
      Create as many volume types as the number of Service Level and Workload
      (available) combinations which you are going to use for provisioning
      volumes. The ``pool_name`` is the additional property which has to be set
      and is of the format: ``<ServiceLevel>+<Workload>+<SRP>+<Array ID>``.
      This can be obtained from the output of the ``cinder get-pools --detail``.

#. For migrating a volume from one Service Level or Workload combination to
   another, use volume retype with the migration-policy to on-demand. The
   target volume type should have the same ``volume_backend_name`` configured
   and should have the desired ``pool_name`` to which you are trying to retype
   to.

   .. code-block:: console

      $ cinder retype --migration-policy on-demand <volume> <volume-type>
