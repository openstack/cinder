======================================
Dell EMC PowerMax iSCSI and FC drivers
======================================

The Dell EMC PowerMax drivers, ``PowerMaxISCSIDriver`` and
``PowerMaxFCDriver``, support the use of Dell EMC PowerMax and VMAX storage
arrays with the Cinder Block Storage project. They both provide equivalent
functions and differ only in support for their respective host attachment
methods.

The drivers perform volume operations by communicating with the back-end
PowerMax storage management software. They use the Requests HTTP library to
communicate with a Unisphere for PowerMax instance, using a RESTAPI interface
in the backend to perform PowerMax and VMAX storage operations.

.. note::

   While ``PowerMax`` will be used throughout this document, it will be used
   to collectively categorize the following supported arrays, PowerMax 2000,
   8000, VMAX All Flash 250F, 450F, 850F and 950F and VMAX Hybrid. Please note
   there will be extended support of the VMAX Hybrid series until further
   notice.


System requirements and licensing
=================================

The Dell EMC PowerMax Cinder driver supports the VMAX-3 hybrid series, VMAX
All-Flash series and the PowerMax arrays.

The array operating system software, Solutions Enabler 9.1.x series, and
Unisphere for PowerMax 9.1.x series are required to run Dell EMC PowerMax
Cinder driver.

Download Solutions Enabler and Unisphere from the Dell EMC's support web site
(login is required). See the ``Dell EMC Solutions Enabler 9.1.x Installation
and Configuration Guide`` and ``Dell EMC Unisphere for PowerMax Installation
Guide`` at the `Dell EMC Support`_ site.

.. note::

   While it is not explicitly documented  which OS versions should be
   installed on a particular array, it is recommended to install the latest
   PowerMax OS as supported by Unisphere for PowerMax, that the PowerMax
   driver supports for a given OpenStack release.

   +-----------+------------------------+-------------+
   | OpenStack | Unisphere for PowerMax | PowerMax OS |
   +===========+========================+=============+
   | Ussuri    | 9.1.x                  | 5978.479    |
   +-----------+------------------------+-------------+
   | Train     | 9.1.x                  | 5978.444    |
   +-----------+------------------------+-------------+
   | Stein     | 9.0.x                  | 5978.221    |
   +-----------+------------------------+-------------+

   However, a Hybrid array can only run HyperMax OS 5977, and is still
   supported until further notice. Some functionality will not be available
   in older versions of the OS.  If in any doubt, please contact your customer
   representative.



Required PowerMax software suites for OpenStack
-----------------------------------------------

The storage system requires a Unisphere for PowerMax (SMC) eLicense.

PowerMax
~~~~~~~~
There are two licenses for the PowerMax 2000 and 8000:

- Essentials software package
- Pro software package

The Dell EMC PowerMax cinder driver requires the Pro software package.

All Flash
~~~~~~~~~
For full functionality including SRDF for the VMAX All Flash, the FX package,
or the F package plus the SRDF a la carte add on is required.

Hybrid
~~~~~~

There are five Dell EMC Software Suites sold with the VMAX Hybrid arrays:

- Base Suite
- Advanced Suite
- Local Replication Suite
- Remote Replication Suite
- Total Productivity Pack

The Dell EMC PowerMax Cinder driver requires the Advanced Suite and the Local
Replication Suite or the Total Productivity Pack (it includes the Advanced
Suite and the Local Replication Suite) for the VMAX Hybrid.

Using PowerMax Remote Replication functionality will also require the Remote
Replication Suite.


.. note::

   Each are licensed separately. For further details on how to get the
   relevant license(s), reference eLicensing Support below.


eLicensing support
------------------

To activate your entitlements and obtain your PowerMax license files, visit the
Service Center on `Dell EMC Support`_, as directed on your License
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


PowerMax for OpenStack Cinder customer support
----------------------------------------------

If you require help or assistance with PowerMax and Cinder please open a
Service Request (SR) through standard support channels at `Dell EMC Support`_.
When opening a SR please include the following information:

- Array Model & uCode level
- Unisphere for PowerMax version
- Solutions Enabler Version
- OpenStack host Operating System (Ubuntu, RHEL, etc.)
- OpenStack version (Usurri, Train, etc.)
- PowerMax for Cinder driver version, this can be located in the comments in
  the PowerMax driver file:
  ``{cinder_install_dir}/cinder/volume/drivers/dell_emc/powermax/fc.py``
- Cinder logs
- Detailed description of the issue you are encountering


Supported operations
====================

PowerMax drivers support these operations:

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
-  List Manageable Volumes/Snapshots
-  Backup create, delete, list, restore and show

PowerMax drivers also support the following features:

-  Dynamic masking view creation
-  Dynamic determination of the target iSCSI IP address
-  iSCSI multipath support
-  Oversubscription
-  Service Level support
-  SnapVX support
-  Compression support(All Flash and PowerMax)
-  Deduplication support(PowerMax)
-  CHAP Authentication
-  Multi-attach support
-  Volume Metadata in logs
-  Encrypted Volume support
-  Extending attached volume
-  Replicated volume retype support
-  Retyping attached(in-use) volume
-  Unisphere High Availability(HA) support
-  Online device expansion of a metro device
-  Rapid TDEV deallocation of deletes
-  Multiple replication devices
-  PowerMax array and storage group tagging
-  Short host name and port group templates


PowerMax naming conventions
===========================

.. note::

   ``shortHostName`` will be altered using the following formula, if its length
   exceeds 16 characters. This is because the storage group and masking view
   names cannot exceed 64 characters:

   .. code-block:: text

      if len(shortHostName) > 16:
          1. Perform md5 hash on the shortHostName
          2. Convert output of 1. to hex
          3. Take last 6 characters of shortHostName and append output of 2.
          4. If the length of output of 3. exceeds 16 characters, join the
             first 8 characters and last 8 characters.

.. note::

   ``portgroup_name`` will be altered using the following formula, if its
   length exceeds 12 characters. This is because the storage group and masking
   view names cannot exceed 64 characters:

   .. code-block:: text

      if len(portgroup_name) > 12:
          1. Perform md5 hash on the portgroup_name
          2. Convert output of 1. to hex
          3. Take last 6 characters of portgroup_name and append output of 2.
          4. If the length of output of 3. exceeds 12 characters, join the
             first 6 characters and last 6 characters.


Masking view names
------------------

Masking views are dynamically created by the PowerMax FC and iSCSI drivers
using the following naming conventions. ``[protocol]`` is either ``I`` for
volumes attached over iSCSI or ``F`` for volumes attached over Fibre Channel.

.. code-block:: text

   OS-[shortHostName]-[protocol]-[portgroup_name]-MV

Initiator group names
---------------------

For each host that is attached to PowerMax volumes using the drivers, an
initiator group is created or re-used (per attachment type). All initiators
of the appropriate type known for that host are included in the group. At
each new attach volume operation, the PowerMax driver retrieves the initiators
(either WWNNs or IQNs) from OpenStack and adds or updates the contents of the
Initiator Group as required. Names are of the following format. ``[protocol]``
is either ``I`` for volumes attached over iSCSI or ``F`` for volumes attached
over Fibre Channel.

.. code-block:: console

   OS-[shortHostName]-[protocol]-IG

.. note::

   Hosts attaching to OpenStack managed PowerMax storage cannot also attach to
   storage on the same PowerMax that are not managed by OpenStack.

FA port groups
--------------

PowerMax array FA ports to be used in a new masking view are retrieved from the
port group provided as the extra spec on the volume type, or chosen from the
list provided in the Dell EMC configuration file.

Storage group names
-------------------

As volumes are attached to a host, they are either added to an existing
storage group (if it exists) or a new storage group is created and the volume
is then added. Storage groups contain volumes created from a pool, attached
to a single host, over a single connection type (iSCSI or FC). ``[protocol]``
is either ``I`` for volumes attached over iSCSI or ``F`` for volumes attached
over Fibre Channel. PowerMax Cinder driver utilizes cascaded storage groups -
a ``parent`` storage group which is associated with the masking view, which
contains ``child`` storage groups for each configured
SRP/slo/workload/compression-enabled or disabled/replication-enabled or
disabled combination.

PowerMax, VMAX All Flash and Hybrid

Parent storage group:

.. code-block:: text

   OS-[shortHostName]-[protocol]-[portgroup_name]-SG

Child storage groups:

.. code-block:: text

   OS-[shortHostName]-[SRP]-[ServiceLevel/Workload]-[portgroup_name]-CD-RE

.. note::

   CD and RE are only set if compression is explicitly disabled or replication
   explicitly enabled. See the compression `11. All Flash compression support`_
   and replication `Volume replication support`_ sections below.

.. note::

   For VMAX All Flash with PowerMax OS (5978) or greater, workload if set will
   be ignored and set to NONE.


PowerMax driver integration
===========================

1. Prerequisites
----------------

#. Download Solutions Enabler from `Dell EMC Support`_ and install it.

   You can install Solutions Enabler on a non-OpenStack host. Supported
   platforms include different flavors of Windows, Red Hat, and SUSE Linux.
   Solutions Enabler can be installed on a physical server, or as a Virtual
   Appliance (a VMware ESX server VM). Additionally, starting with HYPERMAX
   OS Q3 2015, you can manage VMAX3 arrays using the Embedded Management
   (eManagement) container application. See the ``Dell EMC Solutions Enabler
   9.1.x Installation and Configuration Guide`` on `Dell EMC Support`_ for
   more details.

   .. note::

      You must discover storage arrays before you can use the PowerMax drivers.
      Follow instructions in ``Dell EMC Solutions Enabler 9.1.x Installation
      and Configuration Guide`` on `Dell EMC Support`_ for more details.

#. Download Unisphere from `Dell EMC Support`_ and install it.

   Unisphere can be installed in local, remote, or embedded configurations
   - i.e., on the same server running Solutions Enabler; on a server
   connected to the Solutions Enabler server; or using the eManagement
   container application (containing Solutions Enabler and Unisphere for
   PowerMax). See ``Dell EMC Solutions Enabler 9.1.x Installation and
   Configuration Guide`` at `Dell EMC Support`_.


2. FC zoning with PowerMax
--------------------------

Zone Manager is required when there is a fabric between the host and array.
This is necessary for larger configurations where pre-zoning would be too
complex and open-zoning would raise security concerns.

3. iSCSI with PowerMax
----------------------

-  Make sure the ``open-iscsi`` package (or distro equivalent) is installed
   on all Compute nodes.

.. note::

   You can only ping the PowerMax iSCSI target ports when there is a valid
   masking view. An attach operation creates this masking view.



4. Configure block storage in cinder.conf
-----------------------------------------

.. note::

   VMAX driver was rebranded to PowerMax in Stein, so some of the driver
   specific tags have also changed. Legacy tags like ``vmax_srp``,
   ``vmax_array``, ``vmax_service_level`` and ``vmax_port_group``, as well
   as the old driver location, will continue to work until the 'V' release.


.. config-table::
   :config-target: PowerMax

   cinder.volume.drivers.dell_emc.powermax.common


.. note::

   ``san_api_port`` is ``8443`` by default but can be changed if
   necessary. For the purposes of this documentation the default is
   assumed so the tag will not appear in any of the ``cinder.conf``
   extracts below.


.. note::

   PowerMax ``PortGroups`` must be pre-configured to expose volumes managed
   by the array. Port groups can be supplied in ``cinder.conf``, or
   can be specified as an extra spec ``storagetype:portgroupname`` on a
   volume type. The latter gives the user more control. When a dynamic
   masking view is created by the PowerMax driver, if there is no port group
   specified as an extra specification, the port group is chosen randomly
   from the PortGroup list, to evenly distribute load across the set of
   groups provided.

.. note::

   Service Level can be added to ``cinder.conf`` when the backend is the
   default case and there is no associated volume type. This not a recommended
   configuration as it is too restrictive. Workload is ``NONE`` for PowerMax
   and any All Flash with PowerMax OS (5978) or greater.

   +--------------------+----------------------------+----------+----------+
   | PowerMax parameter | cinder.conf parameter      | Default  | Required |
   +====================+============================+==========+==========+
   |  ``ServiceLevel``  | ``powermax_service_level`` | ``None`` | No       |
   +--------------------+----------------------------+----------+----------+


To configure PowerMax block storage, add the following entries to
``/etc/cinder/cinder.conf``:

.. code-block:: ini

   enabled_backends = CONF_GROUP_ISCSI, CONF_GROUP_FC

   [CONF_GROUP_ISCSI]
   volume_driver = cinder.volume.drivers.dell_emc.powermax.iscsi.PowerMaxISCSIDriver
   volume_backend_name = POWERMAX_ISCSI
   powermax_port_groups = [OS-ISCSI-PG]
   san_ip = 10.10.10.10
   san_login = my_username
   san_password = my_password
   powermax_array = 000123456789
   powermax_srp = SRP_1


   [CONF_GROUP_FC]
   volume_driver = cinder.volume.drivers.dell_emc.powermax.fc.PowerMaxFCDriver
   volume_backend_name = POWERMAX_FC
   powermax_port_groups = [OS-FC-PG]
   san_ip = 10.10.10.10
   san_login = my_username
   san_password = my_password
   powermax_array = 000123456789
   powermax_srp = SRP_1

In this example, two back-end configuration groups are enabled:
``CONF_GROUP_ISCSI`` and ``CONF_GROUP_FC``. Each configuration group has a
section describing unique parameters for connections, drivers and the
``volume_backend_name``.


5. SSL support
--------------

#. Get the CA certificate of the Unisphere server. This pulls the CA cert file
   and saves it as ``.pem`` file:

   .. code-block:: console

      # openssl s_client -showcerts \
                         -connect my_unisphere_host:8443 \
                         </dev/null 2>/dev/null \
                         | openssl x509 -outform PEM > my_unisphere_host.pem

   Where ``my_unisphere_host`` is the hostname of the unisphere instance and
   ``my_unisphere_host.pem`` is the name of the ``.pem`` file.

#. Add this path to ``cinder.conf`` under the PowerMax backend stanza and set
   SSL verify to ``True``

   .. code-block:: console

      driver_ssl_cert_verify = True
      driver_ssl_cert_path = /path/to/my_unisphere_host.pem

   ``OR`` follow the steps 3-6 below if you would like to add the CA cert to
   the system certificate bundle instead of specifying the path to cert:

#. OPTIONAL: Copy the ``.pem`` cert to the system certificate
   directory and convert to ``.crt``:

   .. code-block:: console

      # cp my_unisphere_host.pem /usr/share/ca-certificates/ca_cert.crt

#. OPTIONAL: Update CA certificate database with the following command. Ensure
   you select to enable the cert from step 3 when prompted:

   .. code-block:: console

      # sudo dpkg-reconfigure ca-certificates

#. OPTIONAL: Set a system environment variable to tell the Requests library to
   use the system cert bundle instead of the default Certifi bundle:

   .. code-block:: console

      # export REQUESTS_CA_BUNDLE = /etc/ssl/certs/ca-certificates.crt

#. OPTIONAL: Set cert verification to ``True`` under the PowerMax backend
   stanza in ``cinder.conf``:

   .. code-block:: console

      # driver_ssl_cert_verify = True

#. Ensure ``driver_ssl_cert_verify`` is set to ``True`` in ``cinder.conf``
   backend stanzas if steps 3-6 are followed, otherwise ensure both
   ``driver_ssl_cert_path`` and ``driver_ssl_cert_verify`` are set in
   ``cinder.conf`` backend stanzas.


6. Create volume types
----------------------

Once ``cinder.conf`` has been updated, `Openstack CLI`_ commands need to be
issued in order to create and associate OpenStack volume types with the
declared ``volume_backend_names``.

Additionally, each volume type will need an associated ``pool_name`` - an
extra specification indicating the service level/ workload combination to
be used for that volume type.


.. note::

   The ``pool_name`` is an additional property which has to be set and is of
   the format: ``<ServiceLevel>+<SRP>+<Array ID>``. This can be obtained from
   the output of the ``cinder get-pools--detail``. Workload is NONE for
   PowerMax or any All Flash with PowerMax OS (5978) or greater.


There is also the option to assign a port group to a volume type by
setting the ``storagetype:portgroupname`` extra specification.


.. code-block:: console

   $ openstack volume type create POWERMAX_ISCSI_SILVER
   $ openstack volume type set --property volume_backend_name=ISCSI_backend \
                               --property pool_name=Silver+SRP_1+000123456789 \
                               --property storagetype:portgroupname=OS-PG2 \
                               POWERMAX_ISCSI_SILVER
   $ openstack volume type create POWERMAX_FC_DIAMOND
   $ openstack volume type set --property volume_backend_name=FC_backend \
                               --property pool_name=Gold+SRP_1+000123456789 \
                               --property storagetype:portgroupname=OS-PG1 \
                               POWERMAX_FC_GOLD


By issuing these commands, the Block Storage volume type
``POWERMAX_ISCSI_SILVER`` is associated with the ``ISCSI_backend``, a Silver
Service Level.

The type ``POWERMAX_FC_DIAMOND`` is associated with the ``FC_backend``, a
Diamond Service Level.

The ``ServiceLevel`` manages the underlying storage to provide expected
performance. Setting the ``ServiceLevel`` to ``None`` means that non-FAST
managed storage groups will be created instead (storage groups not
associated with any service level).

.. code-block:: console

   openstack volume type set --property pool_name=None+SRP_1+000123456789

.. note::

   PowerMax and Hybrid support ``Diamond``, ``Platinum``, ``Gold``, ``Silver``,
   ``Bronze``, ``Optimized``, and ``None`` service levels. VMAX All Flash
   running HyperMax OS (5977) supports ``Diamond`` and ``None``. Hybrid and All
   Flash support ``DSS_REP``, ``DSS``, ``OLTP_REP``, ``OLTP``, and ``None``
   workloads, the latter up until ucode 5977. Please refer to Stein PowerMax
   online documentation if you wish to use ``workload``. There is no support
   for workloads in PowerMax OS (5978) or greater. These will be silently
   ignored if set for VMAX All-Flash arrays which have been upgraded to
   PowerMax OS (5988).


7. Interval and retries
-----------------------

By default, ``interval`` and ``retries`` are ``3`` seconds and ``200`` retries
respectively. These determine how long (``interval``) and how many times
(``retries``) a user is willing to wait for a single Rest call,
``3*200=600seconds``. Depending on usage, these may need to be overridden by
the user in ``cinder.conf``. For example, if performance is a factor, then the
``interval`` should be decreased to check the job status more frequently, and
if multiple concurrent provisioning requests are issued then ``retries``
should be increased so calls will not timeout prematurely.

In the example below, the driver checks every 3 seconds for the status of the
job. It will continue checking for 200 retries before it times out.

Add the following lines to the PowerMax backend in ``cinder.conf``:

.. code-block:: console

   [CONF_GROUP_ISCSI]
   volume_driver = cinder.volume.drivers.dell_emc.powermax.iscsi.PowerMaxISCSIDriver
   volume_backend_name = POWERMAX_ISCSI
   powermax_port_groups = [OS-ISCSI-PG]
   san_ip = 10.10.10.10
   san_login = my_username
   san_password = my_password
   powermax_array = 000123456789
   powermax_srp = SRP_1
   interval = 1
   retries = 700

8. CHAP authentication support
------------------------------

This supports one-way initiator CHAP authentication functionality into the
PowerMax backend. With CHAP one-way authentication, the storage array
challenges the host during the initial link negotiation process and expects
to receive a valid credential and CHAP secret in response. When challenged,
the host transmits a CHAP credential and CHAP secret to the storage array.
The storage array looks for this credential and CHAP secret which stored in
the host initiator's initiator group (IG) information in the ACLX database.
Once a positive authentication occurs, the storage array sends an acceptance
message to the host. However, if the storage array fails to find any record
of the credential/secret pair, it sends a rejection message, and the link is
closed.

Assumptions, restrictions and prerequisites
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. The host initiator IQN is required along with the credentials the host
   initiator will use to log into the storage array with. The same credentials
   should be used in a multi node system if connecting to the same array.

#. Enable one-way CHAP authentication for the iSCSI initiator on the storage
   array using ``SYMCLI``. Template and example shown below. For the purpose of
   this setup, the credential/secret used would be ``my_username/my_password``
   with iSCSI initiator of ``iqn.1991-05.com.company.lcseb130``

   .. code-block:: console

      # symaccess -sid <SymmID> -iscsi <iscsi> \
                  {enable chap | disable chap | set chap} \
                   -cred <Credential> -secret <Secret>

      # symaccess -sid 128 \
                  -iscsi iqn.1991-05.com.company.lcseb130 \
                  set chap -cred my_username -secret my_password



Settings and configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Set the configuration in the PowerMax backend group in ``cinder.conf`` using
   the following parameters and restart cinder.

   +-----------------------+-------------------------+-------------------+
   | Configuration options | Value required for CHAP | Required for CHAP |
   +=======================+=========================+===================+
   |  ``use_chap_auth``    | ``True``                | Yes               |
   +-----------------------+-------------------------+-------------------+
   |  ``chap_username``    | ``my_username``         | Yes               |
   +-----------------------+-------------------------+-------------------+
   |  ``chap_password``    | ``my_password``         | Yes               |
   +-----------------------+-------------------------+-------------------+

   .. code-block:: ini

      [POWERMAX_ISCSI]
      volume_driver = cinder.volume.drivers.dell_emc.powermax.iscsi.PowerMaxISCSIDriver
      volume_backend_name = POWERMAX_ISCSI
      san_ip = 10.10.10.10
      san_login = my_u4v_username
      san_password = my_u4v_password
      powermax_srp = SRP_1
      powermax_array = 000123456789
      powermax_port_groups = [OS-ISCSI-PG]
      use_chap_auth = True
      chap_username = my_username
      chap_password = my_password


Usage
~~~~~

#. Using ``SYMCLI``, enable CHAP authentication for a host initiator as
   described above, but do not set ``use_chap_auth``, ``chap_username`` or
   ``chap_password`` in ``cinder.conf``. Create a bootable volume.

   .. code-block:: console

      openstack volume create --size 1 \
                              --image <image_name> \
                              --type <volume_type> \
                              test

#. Boot instance named ``test_server`` using the volume created above:

   .. code-block:: console

      openstack server create --volume test \
                              --flavor m1.small \
                              --nic net-id=private \
                              test_server

#. Verify the volume operation succeeds but the boot instance fails as
   CHAP authentication fails.

#. Update ``cinder.conf`` with ``use_chap_auth`` set to true and
   ``chap_username`` and ``chap_password`` set with the correct credentials.

#. Rerun ``openstack server create``

#. Verify that the boot instance operation ran correctly and the volume is
   accessible.

#. Verify that both the volume and boot instance operations ran successfully
   and the user is able to access the volume.



9. QoS (Quality of Service) support
-----------------------------------

Quality of service (QoS) has traditionally been associated with network
bandwidth usage. Network administrators set limitations on certain networks
in terms of bandwidth usage for clients. This enables them to provide a
tiered level of service based on cost. The Nova/Cinder QoS offer similar
functionality based on volume type setting limits on host storage bandwidth
per service offering. Each volume type is tied to specific QoS attributes
some of which are unique to each storage vendor. In the hypervisor, the QoS
limits the following:

- Limit by throughput - Total bytes/sec, read bytes/sec, write bytes/sec
- Limit by IOPS - Total IOPS/sec, read IOPS/sec, write IOPS/sec

QoS enforcement in Cinder is done either at the hyper-visor (front-end),
the storage subsystem (back-end), or both. This section focuses on QoS
limits that are enforced by either the PowerMax backend and the hyper-visor
front end interchangeably or just back end (Vendor Specific). The PowerMax
driver offers support for Total bytes/sec limit in throughput and Total
IOPS/sec limit of IOPS.

The PowerMax driver supports the following attributes that are front
end/back end agnostic

- ``total_iops_sec`` - Maximum IOPs (in I/Os per second). Valid values range
  from 100 IO/Sec to 100000 IO/sec.
- ``total_bytes_sec`` - Maximum bandwidth (throughput) in bytes per second.
  Valid values range from 1048576 bytes (1MB) to 104857600000 bytes (100,000MB)

The PowerMax driver offers the following attribute that is vendor specific to
the PowerMax and dependent on the ``total_iops_sec`` and/or ``total_bytes_sec``
being set.

- ``Dynamic Distribution`` - Enables/Disables dynamic distribution of host I/O
  limits. Possible values are:

  - ``Always`` - Enables full dynamic distribution mode. When enabled, the
    configured host I/O limits will be dynamically distributed across the
    configured ports, thereby allowing the limits on each individual port to
    adjust to fluctuating demand.
  - ``OnFailure`` - Enables port failure capability. When enabled, the fraction
    of configured host I/O limits available to a configured port will adjust
    based on the number of ports currently online.
  - ``Never`` - Disables this feature (Default).

USE CASE 1 - Default values
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prerequisites - PowerMax

- Host I/O Limit (MB/Sec) -     No Limit
- Host I/O Limit (IO/Sec) -     No Limit
- Set Dynamic Distribution -    N/A

.. table:: **Prerequisites - Block Storage (Cinder) back-end (storage group)**

 +-----------------------+-----------------------+
 |  Key                  | Value                 |
 +=======================+=======================+
 |  ``total_iops_sec``   |  ``500``              |
 +-----------------------+-----------------------+
 |  ``total_bytes_sec``  | ``104857600`` (100MB) |
 +-----------------------+-----------------------+
 |  ``DistributionType`` | ``Always``            |
 +-----------------------+-----------------------+

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

**Outcome - PowerMax (storage group)**

- Host I/O Limit (MB/Sec) -     ``100``
- Host I/O Limit (IO/Sec) -     ``500``
- Set Dynamic Distribution -    ``Always``

**Outcome - Block Storage (Cinder)**

Volume is created against volume type and QoS is enforced with the parameters
above.

USE CASE 2 - Pre-set limits
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prerequisites - PowerMax

- Host I/O Limit (MB/Sec) -     ``2000``
- Host I/O Limit (IO/Sec) -     ``2000``
- Set Dynamic Distribution -    ``Never``

.. table:: **Prerequisites - Block Storage (Cinder) back-end (storage group)**

 +-----------------------+-----------------------+
 |  Key                  | Value                 |
 +=======================+=======================+
 |  ``total_iops_sec``   |  ``500``              |
 +-----------------------+-----------------------+
 |  ``total_bytes_sec``  | ``104857600`` (100MB) |
 +-----------------------+-----------------------+
 |  ``DistributionType`` | ``Always``            |
 +-----------------------+-----------------------+

#. Create QoS specifications with the prerequisite values above. The consumer
   in this use case is both for front-end and back-end:

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

**Outcome - PowerMax (storage group)**

- Host I/O Limit (MB/Sec) -     ``100``
- Host I/O Limit (IO/Sec) -     ``500``
- Set Dynamic Distribution -    ``Always``

**Outcome - Block Storage (Cinder)**

Volume is created against volume type and QoS is enforced with the parameters
above.

**Outcome - Hypervisor (Nova)**

``Libvirt`` includes an extra ``xml`` flag within the ``<disk>`` section called
``iotune`` that is responsible for rate limitation. To confirm that, first get
the ``OS-EXT-SRV-ATTR:instance_name`` value of the server instance,
for example ``instance-00000003``.

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

We then run the following command using the ``OS-EXT-SRV-ATTR:instance_name``
retrieved above.

.. code-block:: console

   $ virsh dumpxml instance-00000003 | grep -1 "total_bytes_sec\|total_iops_sec"

The output of the command contains the XML below. It is found between the
``<disk>`` start and end tag.

.. code-block:: xml

   <iotune>
      <total_bytes_sec>104857600</total_bytes_sec>
      <total_iops_sec>500</total_iops_sec>
   </iotune>


USE CASE 3 - Pre-set limits
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prerequisites - PowerMax

- Host I/O Limit (MB/Sec) -     ``100``
- Host I/O Limit (IO/Sec) -     ``500``
- Set Dynamic Distribution -    ``Always``

.. table:: **Prerequisites - Block Storage (Cinder) back end (storage group)**

 +-----------------------+-----------------------+
 |  Key                  | Value                 |
 +=======================+=======================+
 |  ``total_iops_sec``   |  ``500``              |
 +-----------------------+-----------------------+
 |  ``total_bytes_sec``  | ``104857600`` (100MB) |
 +-----------------------+-----------------------+
 |  ``DistributionType`` | ``OnFailure``         |
 +-----------------------+-----------------------+

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

**Outcome - PowerMax (storage group)**

- Host I/O Limit (MB/Sec) -     ``100``
- Host I/O Limit (IO/Sec) -     ``500``
- Set Dynamic Distribution -    ``OnFailure``

**Outcome - Block Storage (Cinder)**

Volume is created against volume type and QOS is enforced with the parameters
above.


USE CASE 4 - Default values
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prerequisites - PowerMax

- Host I/O Limit (MB/Sec) -     ``No Limit``
- Host I/O Limit (IO/Sec) -     ``No Limit``
- Set Dynamic Distribution -    ``N/A``

.. table:: **Prerequisites - Block Storage (Cinder) back end (storage group)**

 +-----------------------+---------------+
 |  Key                  | Value         |
 +=======================+===============+
 |  ``DistributionType`` | ``Always``    |
 +-----------------------+---------------+

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

**Outcome - PowerMax (storage group)**

- Host I/O Limit (MB/Sec) -     ``No Limit``
- Host I/O Limit (IO/Sec) -     ``No Limit``
- Set Dynamic Distribution -    ``N/A``

**Outcome - Block Storage (Cinder)**

Volume is created against volume type and there is no QoS change.

10. iSCSI multi-pathing support
-------------------------------

- Install ``open-iscsi`` on all nodes on your system
- Do not install EMC PowerPath as they cannot co-exist with native multi-path
  software
- Multi-path tools must be installed on all Nova compute nodes

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The multi-path configuration file may be edited for better management and
performance. Log in as a privileged user and make the following changes to
``/etc/multipath.conf`` on the  Compute (Nova) node(s).

.. code-block:: vim

   devices {
   # Device attributed for EMC PowerMax
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
iSCSI and multi-path services.

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
~~~~~~~~~~~~~~~~~~~~~~~~

On Compute (Nova) node, add the following flag in the ``[libvirt]`` section of
``nova.conf`` and ``nova-cpu.conf``:

.. code-block:: ini

   volume_use_multipath = True

On Cinder controller node, multi-path for image transfer can be enabled in
``cinder.conf`` for each backend section or in ``[backend_defaults]`` section
as a common configuration for all backends.

.. code-block:: ini

   use_multipath_for_image_xfer = True

Restart ``nova-compute`` and ``cinder-volume`` services after the change.

Verify you have multiple initiators available on the compute node for I/O
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Create a 3GB PowerMax volume.
#. Create an instance from image out of native LVM storage or from PowerMax
   storage, for example, from a bootable volume
#. Attach the 3GB volume to the new instance:

   .. code-block:: console

      # multipath -ll
      mpath102 (360000970000196700531533030383039) dm-3 EMC,SYMMETRIX
      size=3G features='1 queue_if_no_path' hwhandler='0' wp=rw
      '-+- policy='round-robin 0' prio=1 status=active
      33:0:0:1 sdb 8:16 active ready running
      '- 34:0:0:1 sdc 8:32 active ready running

#. Use the ``lsblk`` command to see the multi-path device:

   .. code-block:: console

      # lsblk
      NAME                                       MAJ:MIN RM   SIZE RO TYPE
      sdb                                          8:0    0     3G  0 disk
      ..360000970000196700531533030383039 (dm-6) 252:6    0     3G  0 mpath
      sdc                                          8:16   0     3G  0 disk
      ..360000970000196700531533030383039 (dm-6) 252:6    0     3G  0 mpath
      vda


11. All Flash compression support
---------------------------------

On an All Flash array, the creation of any storage group has a compressed
attribute by default. Setting compression on a storage group does not mean
that all the devices will be immediately compressed. It means that for all
incoming writes compression will be considered. Setting compression ``off`` on
a storage group does not mean that all the devices will be uncompressed.
It means all the writes to compressed tracks will make these tracks
uncompressed.

.. note::

   This feature is only applicable for All Flash arrays, 250F, 450F, 850F
   and 950F and PowerMax 2000 and 8000. It was first introduced Solutions
   Enabler 8.3.0.11 or later and is enabled by default when associated with
   a Service Level. This means volumes added to any newly created storage
   groups will be  compressed.

Use case 1 - Compression disabled create, attach, detach, and delete volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Create a new volume type called ``POWERMAX_COMPRESSION_DISABLED``.
#. Set an extra spec ``volume_backend_name``.
#. Set a new extra spec ``storagetype:disablecompression = True``.
#. Create a new volume.
#. Check in Unisphere or SYMCLI to see if the volume
   exists in storage group ``OS-<srp>-<servicelevel>-<workload>-CD-SG``, and
   compression is disabled on that storage group.
#. Attach the volume to an instance. Check in Unisphere or SYMCLI to see if the
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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Repeat steps 1-4 of Use case 1.
#. Create a new volume type. For example ``POWERMAX_COMPRESSION_ENABLED``.
#. Set extra spec ``volume_backend_name`` as before.
#. Set the new extra spec's compression as
   ``storagetype:disablecompression = False`` or DO NOT set this extra spec.
#. Retype from volume type ``POWERMAX_COMPRESSION_DISABLED`` to
   ``POWERMAX_COMPRESSION_ENABLED``.
#. Check in Unisphere or symcli to see if the volume exists in storage group
   ``OS-<srp>-<servicelevel>-<workload>-SG``, and compression is enabled on
   that storage group.

.. note::
   If extra spec ``storagetype:disablecompression`` is set on a Hybrid, it is
   ignored because compression is not an available feature on a VMAX3 Hybrid.


12. Oversubscription support
----------------------------

Please refer to the official OpenStack `over-subscription documentation`_ for
further information on using over-subscription with PowerMax.


13. Live migration support
--------------------------

**Non-live migration** (sometimes referred to simply as 'migration'). The
instance is shut down for a period of time to be moved to another hyper-visor.
In this case, the instance recognizes that it was rebooted.

**Live migration** (or 'true live migration'). Almost no instance downtime.
Useful when the instances must be kept running during the migration. The
different types of live migration are:

- **Shared storage-based live migration** Both hyper-visors have access to
  shared storage.

- **Block live migration** No shared storage is required. Incompatible with
  read-only devices such as CD-ROMs and Configuration Drive (config_drive).

- **Volume-backed live migration** Instances are backed by volumes rather than
  ephemeral disk.  For PowerMax volume-backed live migration, shared storage
  is required.

The PowerMax driver supports shared volume-backed live migration.

Architecture
~~~~~~~~~~~~

In PowerMax, A volume cannot belong to two or more FAST storage groups at the
same time. To get around this limitation we leverage both cascaded storage
groups and a temporary non-FAST storage group.

A volume can remain 'live' if moved between masking views that have the same
initiator group and port groups which preserves the host path.

During live migration, the following steps are performed by the PowerMax driver
on the volume:

#. Within the originating masking view, the volume is moved from the FAST
   storage group to the non-FAST storage group within the parent storage
   group.
#. The volume is added to the FAST storage group within the destination
   parent storage group of the destination masking view. At this point the
   volume belongs to two storage groups.
#. One of two things happen:

   - If the connection to the destination instance is successful, the volume
     is removed from the non-FAST storage group in the originating masking
     view, deleting the storage group if it contains no other volumes.
   - If the connection to the destination instance fails, the volume is
     removed from the destination storage group, deleting the storage group,
     if empty. The volume is reverted back to the original storage group.


Live migration configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Please refer to the official OpenStack documentation on
`configuring migrations`_ and `live migration usage`_ for more information.

.. note::

   OpenStack Oslo uses an open standard for messaging middleware known as
   ``AMQP``. This messaging middleware (the RPC messaging system) enables the
   OpenStack services that run on multiple servers to talk to each other.
   By default, the RPC messaging client is set to timeout after 60 seconds,
   meaning if any operation you perform takes longer than 60 seconds to
   complete the operation will timeout and fail with the ERROR message
   ``Messaging Timeout: Timed out waiting for a reply to message ID``
   ``[message_id]``

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
   sufficient for all Cinder backup commands also.


System configuration
~~~~~~~~~~~~~~~~~~~~

``NOVA-INST-DIR/instances/`` (for example, ``/opt/stack/data/nova/instances``)
has to be mounted by shared storage. Ensure that ``NOVA-INST-DIR`` (set with
``state_path`` in the ``nova.conf`` file) is the same on all hosts.

#. Configure your DNS or ``/etc/hosts`` and ensure it is consistent across all
   hosts. Make sure that the three hosts can perform name resolution with each
   other. As a test, use the ping command to ping each host from one another.

   .. code-block:: console

      $ ping HostA
      $ ping HostB
      $ ping HostC

#. Export ``NOVA-INST-DIR/instances`` from ``HostA``, and ensure it is readable
   and writable by the Compute user on ``HostB`` and ``HostC``. Please refer to
   the relevant OS documentation for further details, for example
   `Ubuntu NFS Documentation`_

#. On all compute nodes, enable the ``execute/search`` bit on your shared
   directory to allow ``qemu`` to be able to use the images within the
   directories. On all hosts, run the following command:

   .. code-block:: console

       $ chmod o+x NOVA-INST-DIR/instances

.. note::

   If migrating from compute to controller, make sure to run step two above on
   the controller node to export the instance directory.


Use case
~~~~~~~~

For our use case shown below, we have three hosts with host names ``HostA``,
``HostB`` and ``HostC``. ``HostA`` is the controller node while ``HostB`` and
``HostC`` are the compute nodes. The following were also used in live
migration.

- 2GB bootable volume using the CirrOS image.
- Instance created using the 2GB volume above with a flavor ``m1.small`` using
  2048 RAM, 20GB of Disk and 1 VCPU.

#. Create a bootable volume.

   .. code-block:: console

      $ openstack volume create --size 2 \
                                --image cirros-0.3.5-x86_64-disk \
                                --volume_lm_1

#. Launch an instance using the volume created above on ``HostB``.

   .. code-block:: console

      $ openstack server create --volume volume_lm_1 \
                                --flavor m1.small \
                                --nic net-id=private \
                                --security-group default \
                                --availability-zone nova:HostB \
                                server_lm_1

#. Confirm on ``HostB`` has the instance created by running:

   .. code-block:: console

      $ openstack server show server_lm_1 | grep "hypervisor_hostname\|instance_name"
        | OS-EXT-SRV-ATTR:hypervisor_hostname | HostB
        | OS-EXT-SRV-ATTR:instance_name | instance-00000006

#. Confirm, through ``virsh`` using the instance_name returned in step 3
   (``instance-00000006``), on ``HostB`` that the instance is created using:

   .. code-block:: console

      $ virsh list --all

      Id   Name                  State
      --------------------------------
      1    instance-00000006     Running

#. Migrate the instance from ``HostB`` to ``HostA`` with:

   .. code-block:: console

      $ openstack server migrate --live HostA \
                                 server_lm_1

#. Run the command on step 3 above when the instance is back in available
   status. The hypervisor should be on Host A.

#. Run the command on Step 4 on Host A to confirm that the instance is
   created through ``virsh``.


14. Multi-attach support
------------------------

PowerMax cinder driver supports the ability to attach a volume to multiple
hosts/servers simultaneously. Please see the official OpenStack
`multi-attach documentation`_ for configuration information.

Multi-attach architecture
~~~~~~~~~~~~~~~~~~~~~~~~~

In PowerMax, a volume cannot belong to two or more FAST storage groups at the
same time. This can cause issues when we are attaching a volume to multiple
instances on different hosts. To get around this limitation, we leverage both
cascaded storage groups and non-FAST storage groups (i.e. a storage group with
no service level, workload, or SRP specified).

.. note::

   If no service level is assigned to the volume type, no extra work on the
   backend is required – the volume is attached to and detached from each
   host as normal.

Example use case
~~~~~~~~~~~~~~~~

Volume ``Multi-attach-Vol-1`` (with a multi-attach capable volume type, and
associated with a Diamond Service Level) is attached to Instance
``Multi-attach-Instance-A`` on HostA. We then issue the command to attach
``Multi-attach-Vol-1`` to ``Multi-attach-Instance-B`` on HostB:

#. In the ``HostA`` masking view, the volume is moved from the FAST managed
   storage group to the non-FAST managed storage group within the parent
   storage group.

#. The volume is attached as normal on ``HostB`` – i.e., it is added to a FAST
   managed storage group within the parent storage group of the ``HostB``
   masking view. The volume now belongs to two masking views, and is exposed to
   both ``HostA`` and ``HostB``.

We then decide to detach the volume from ``Multi-attach-Instance-B`` on
``HostB``:

#. The volume is detached as normal from ``HostB`` – i.e., it is removed from
   the FAST managed storage group within the parent storage group of the
   ``HostB`` masking view – this includes cleanup of the associated elements
   if required. The volume now belongs to one masking view, and is no longer
   exposed to ``HostB``.

#. In the ``HostA`` masking view, the volume is returned to the FAST managed
   storage group from the non-FAST managed storage group within the parent
   storage group. The non-FAST managed storage group is cleaned up,
   if required.


15. Volume encryption support
-----------------------------

Encryption is supported through the use of OpenStack Barbican. Only front-end
encryption is supported, back-end encryption is handled at the hardware level
with `Data at Rest Encryption`_ (D@RE).

For further information on OpenStack Barbican including setup and configuration
please refer to the following `official Barbican documentation`_.


16. Volume metadata
-------------------

Volume metadata is returned to the user in both the Cinder Volume logs and
with volumes and snapshots created in Cinder via the UI or CLI.

16.1 Volume metadata in logs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If debug is enabled in the default section of ``cinder.conf``, PowerMax Cinder
driver will log additional volume information in the Cinder volume log,
on each successful operation.  The facilitates bridging the gap between
OpenStack and the Array by tracing and describing the volume from a VMAX/
PowerMax view point.

.. code-block:: console

   +------------------------------------+---------------------------------------------------------+
   | Key                                | Value                                                   |
   +------------------------------------+---------------------------------------------------------+
   | service_level                      | Gold                                                    |
   | is_compression_disabled            | no                                                      |
   | powermax_cinder_driver_version     | 3.2.0                                                   |
   | identifier_name                    | OS-819470ab-a6d4-49cc-b4db-6f85e82822b7                 |
   | openstack_release                  | 13.0.0.0b3.dev3                                         |
   | volume_id                          | 819470ab-a6d4-49cc-b4db-6f85e82822b7                    |
   | storage_model                      | PowerMax_8000                                           |
   | successful_operation               | delete                                                  |
   | default_sg_name                    | OS-DEFAULT_SRP-Gold-NONE-SG                             |
   | device_id                          | 01C03                                                   |
   | unisphere_for_powermax_version     | V9.0.0.9                                                |
   | workload                           | NONE                                                    |
   | openstack_version                  | 13.0.0                                                  |
   | volume_updated_time                | 2018-08-03 03:13:53                                     |
   | platform                           | Linux-4.4.0-127-generic-x86_64-with-Ubuntu-16.04-xenial |
   | python_version                     | 2.7.12                                                  |
   | volume_size                        | 20                                                      |
   | srp                                | DEFAULT_SRP                                             |
   | openstack_name                     | 90_Test_Vol56                                           |
   | storage_firmware_version           | 5978.143.144                                            |
   | serial_number                      | 000123456789                                            |
   +------------------------------------+---------------------------------------------------------+

16.2 Metadata in the UI and CLI
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default metadata will be set on all volume and snapshot objects created in
Cinder. This information represents the state of the object on the backend
PowerMax and will change when volume attributes are changed by performing
actions on them such as re-type or attaching to an instance.

.. code-block:: console

   demo@openstack-controller:~$ cinder show powermax-volume

   +--------------------------------+------------------------------------------------------------+
   | Property                       | Value                                                      |
   +--------------------------------+------------------------------------------------------------+
   | metadata                       | ArrayID : 000123456789                                     |
   |                                | ArrayModel : PowerMax_8000                                 |
   |                                | CompressionDisabled : False                                |
   |                                | Configuration : TDEV                                       |
   |                                | DeviceID : 0012F                                           |
   |                                | DeviceLabel : OS-d87edb98-60fd-49dd-bb0f-cc388cf6f3f4      |
   |                                | Emulation : FBA                                            |
   |                                | ReplicationEnabled : False                                 |
   |                                | ServiceLevel : Diamond                                     |
   |                                | Workload : None                                            |
   | name                           | powermax-volume                                            |
   +--------------------------------+------------------------------------------------------------+


17. Unisphere High Availability (HA) support
--------------------------------------------

This feature facilitates high availability of Unisphere for PowerMax servers,
allowing for one or more backup unisphere instances in the event of a loss in
connection to the primary Unisphere instance. The PowerMax driver will
cycle through the list of failover instances, trying each until a successful
connection is made. The ordering is first in, first out (FIFO), so the first
``u4p_failover_target`` specified in ``cinder.conf`` will be the first
selected, the second ``u4p_failover_target`` in ``cinder.conf`` will be the
second selected, and so on until all failover targets are exhausted.

Requirements
~~~~~~~~~~~~

- All required instances of Unisphere for PowerMax are set up and configured
  for the array(s)
- Array(s) are locally registered with the instance of Unisphere that will be
  used as a failover instance. There are two failover types, local and
  remote:

  - `Local failover` - Primary Unisphere is unreachable, failover to
    secondary local instance of Unisphere to resume normal operations at
    primary site.
  - `Remote failover` - Complete loss of primary site so primary instance of
    Unisphere is unreachable, failover to secondary instance of Unisphere at
    remote site to resume operations with the R2 array.

.. note::

   Replication must be configured in advance for remote failover to work
   successfully. Human intervention will also be required to failover from R1
   array to R2 array in Cinder using ``cinder failover-host`` command
   (see `Volume replication support`_ for replication setup details).

.. note::

   The remote target array must be registered as local to the remote instance
   of Unisphere

Configuration
~~~~~~~~~~~~~

The following configuration changes need to be made in ``cinder.conf`` in order
to support the failover to secondary Unisphere. Cinder services will need to
be restarted for changes to take effect.

.. code-block:: console

   u4p_failover_timeout = 30
   u4p_failover_retries = 3
   u4p_failover_backoff_factor = 1
   u4p_failover_autofailback = True
   u4p_failover_target = san_ip:10.10.10.12,
                         san_api_port: 8443,
                         san_login:my_username,
                         san_password:my_password,
                         driver_ssl_cert_verify: False,
   u4p_failover_target = san_ip:10.10.10.13,
                         san_api_port: 8443
                         san_login:my_username,
                         san_password:my_password,
                         driver_ssl_cert_verify: True,
                         driver_ssl_cert_path: /path/to/my_unisphere_host.pem

.. note::

  ``u4p_failover_target`` key value pairs will need to be on the same
  line (separated by commas) in ``cinder.conf``. They are displayed on
  separated lines above for readability.

.. note::

   To add more than one Unisphere failover target create additional
   ``u4p_failover_target`` details for the Unisphere instance. These will be
   cycled through in a first-in, first-out (FIFO) basis, the first failover
   target in ``cinder.conf`` will be the first backup instance of Unisphere
   used by the PowerMax driver.


18. Rapid TDEV deallocation
---------------------------

The PowerMax driver can now leverage the enhanced volume delete feature-set
made available in the PowerMax 5978 Foxtail uCode release. These enhancements
allow volume deallocation & deletion to be combined into a single call.
Previously, volume deallocation & deletion were split into separate tasks;
now a single REST call is dispatched and a response code on the projected
outcome of their request is issued rapidly allowing other task execution to
proceed without the delay. No additional configuration is necessary, the
system will automatically determine when to use either the rapid or legacy
compliant volume deletion sequence based on the connected PowerMax array’s
metadata.


19. PowerMax online (in-use) device expansion
---------------------------------------------

.. table::

   +---------------------------------+-------------------------------------------+
   | uCode Level                     | Supported In-Use Volume Extend Operations |
   +----------------+----------------+--------------+--------------+-------------+
   | R1 uCode Level | R2 uCode Level | Sync         | Async        | Metro       |
   +================+================+==============+==============+=============+
   | 5978.444       | 5978.444       | Y            | Y            | Y           |
   +----------------+----------------+--------------+--------------+-------------+
   | 5978.444       | 5978.221       | Y            | Y            | N           |
   +----------------+----------------+--------------+--------------+-------------+
   | 5978.221       | 5978.221       | Y            | Y            | N           |
   +----------------+----------------+--------------+--------------+-------------+


Assumptions, restrictions and prerequisites
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- ODE in the context of this document refers to extending a volume where it
  is in-use, that is, attached to an instance.
- The ``allow_extend`` is only applicable on Hybrid arrays or All Flash arrays
  with HyperMax OS. If included elsewhere, it is ignored.
- Where one array is a lower uCode than the other, the environment is limited
  to functionality of that of the lowest uCode level, i.e. if R1 is 5978.444
  and R2 is 5978.221, expanding a metro volume is not supported, both R1 and
  R2 need to be on 5978.444 uCode.


20. PowerMax array and storage group tagging
--------------------------------------------

Unisphere for PowerMax 9.1 supports tagging of storage groups and arrays,
so the user can give their own 'tag' for ease of searching and/or grouping.

Assumptions, restrictions and prerequisites
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- The storage group tag(s) is associated with a volume type extra spec key
  ``storagetype:storagegrouptags``.
- The array tag is associated with the backend stanza using key
  ``powermax_array_tag_list``. It expects a list of one or more comma
  separated values, for example
  ``powermax_array_tag_list=[value1,value2, value3]``
- They can be one or more values in a comma separated list.
- There is a 64 characters limit of letters, numbers, - and _.
- 8 tags are allowed per storage group and array.
- Tags cannot be modified once a volume has been created with that volume
  type. This is an OpenStack constraint.
- Tags can be modified on the backend stanza, but none will ever be removed,
  only added.
- There is no restriction on creating or deleting tags of OpenStack storage
  groups or arrays outside of OpenStack, for example  Unisphere for PowerMax
  UI.  The max number of 8 tags will apply however, as this is a Unisphere for
  PowerMax limit.

Set a storage group tag on a volume type:

.. code-block:: console

   $ openstack volume type set --property storagetype:storagegrouptags=myStorageGroupTag1,myStorageGroupTag2


Set an array tag on the PowerMax backend:

.. code-block:: console

   [POWERMAX_ISCSI]
   volume_driver = cinder.volume.drivers.dell_emc.powermax.iscsi.PowerMaxISCSIDriver
   volume_backend_name = POWERMAX_ISCSI
   san_ip = 10.10.10.10
   san_login = my_u4v_username
   san_password = my_u4v_password
   powermax_srp = SRP_1
   powermax_array = 000123456789
   powermax_port_groups = [OS-ISCSI-PG]
   powermax_array_tag_list = [openstack1, openstack2]


21. PowerMax short host name and port group name override
---------------------------------------------------------

This functionality allows the user to customize the short host name and port
group name that are contained in the PowerMax driver storage groups and
masking views names. For current functionality please refer to
`PowerMax naming conventions`_ for more details.

As the storage group name and masking view name are limited to 64 characters
the short host name needs to be truncated to 16 characters or less and port
group needs to be truncated to 12 characters or less.  This functionality
offers a little bit more flexibility to determine how these truncated
components should look.

Assumptions, restrictions, and prerequisites
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Backward compatibility with old format is preserved.
- ``cinder.conf`` will have 2 new configuration options,
  ``short_host_name_template`` and ``port_group_name_template``.
- If a storage group, masking view or initiator group in the old naming
  convention already exists, this remains and any new attaches will use
  the new naming convention where the label for the short host name
  and/or port group has been customized by the user.
- Only the short host name and port group name components can be renamed
  within the storage group, initiator group and masking view names.
- If the ``powermax_short_host_name_template`` and
  ``powermax_port_group_name_template`` do not adhere to the rules, then
  the operation will fail early and gracefully with a clear description as
  to the problem.
- The templates cannot be changed once volumes have been attached using the
  new configuration.
- If only one of the templates are configured, then the other will revert to
  the default option.
- The UUID is generated from the MD5 hash of the full short host name
  and port group name
- If ``userdef`` is used, the onus is on the user to make sure it will be
  unique among all short host names (controller and compute nodes) and
  unique among port groups.


.. table:: Short host name templates

   +-----------------------------------+-------------------------------------+------------------------------------+
   | powermax_short_host_name_template |        Description                  | Rule                               |
   +===================================+=====================================+====================================+
   | shortHostName                     | This is the default option          | Existing functionality, if over 16 |
   |                                   |                                     | characters then see                |
   |                                   |                                     | `PowerMax naming conventions`_,    |
   |                                   |                                     | otherwise short host name          |
   +-----------------------------------+-------------------------------------+------------------------------------+
   | shortHostName[:x])uuid[:x]        | First x characters of the short     | Must be less than 16 characters    |
   | e.g.                              | host name and x uuid                |                                    |
   | shortHostName[:6]uuid[:9]         | characters created from md5         |                                    |
   |                                   | hash of short host name             |                                    |
   +-----------------------------------+-------------------------------------+------------------------------------+
   | shortHostName[:x]userdef          | First x characters of the short     | Must be less than 16 characters    |
   | e.g.                              | host name and a user defined x char |                                    |
   | shortHostName[:6]-testHost        | name. NB - the responsibility is on |                                    |
   |                                   | the user for uniqueness             |                                    |
   +-----------------------------------+-------------------------------------+------------------------------------+
   | shortHostName[-x:]uuid[:x]        | Last x characters of the short      | Must be less than 16 characters    |
   | e.g.                              | host name and x uuid                |                                    |
   | shortHostName[-6:]uuid[:9]        | characters created from md5         |                                    |
   |                                   | hash of short host name             |                                    |
   +-----------------------------------+-------------------------------------+------------------------------------+
   | shortHostName[-x:]userdef         | Last x characters of the short      | Must be less than 16 characters    |
   | e.g.                              | host name and a user defined x char |                                    |
   | shortHostName[-6:]-testHost       | name. NB - the responsibility is on |                                    |
   |                                   | the user for uniqueness             |                                    |
   +-----------------------------------+-------------------------------------+------------------------------------+


.. table:: Port group name templates

   +-----------------------------------+-------------------------------------+------------------------------------+
   | powermax_port_group_name_template |        Description                  | Rule                               |
   +===================================+=====================================+====================================+
   | portGroupName                     | This is the default option          | Existing functionality, if over 12 |
   |                                   |                                     | characters then see                |
   |                                   |                                     | `PowerMax naming conventions`_,    |
   |                                   |                                     | otherwise port group name          |
   +-----------------------------------+-------------------------------------+------------------------------------+
   | portGroupName[:x])uuid[:x]        | First x characters of the port      | Must be less than 12 characters    |
   | e.g.                              | group name and x uuid               |                                    |
   | portGroupName[:6]uuid[:5]         | characters created from md5         |                                    |
   |                                   | hash of port group name             |                                    |
   +-----------------------------------+-------------------------------------+------------------------------------+
   | portGroupName[:x]userdef          | First x characters of the port      | Must be less than 12 characters    |
   | e.g.                              | group name and a user defined x char|                                    |
   | portGroupName[:6]-test            | name. NB - the responsibility is on |                                    |
   |                                   | the user for uniqueness             |                                    |
   +-----------------------------------+-------------------------------------+------------------------------------+
   | portGroupName[-x:]uuid[:x]        | Last x characters of the port       | Must be less than 12 characters    |
   | e.g.                              | group name and x uuid               |                                    |
   | portGroupName[-6:]uuid[:5]        | characters created from md5         |                                    |
   |                                   | hash of port group name             |                                    |
   +-----------------------------------+-------------------------------------+------------------------------------+
   | portGroupName[-x:]userdef         | Last x characters of the port       | Must be less than 12 characters    |
   | e.g.                              | group name and a user defined x char|                                    |
   | portGroupName[-6:]-test           | name. NB - the responsibility is on |                                    |
   |                                   | the user for uniqueness             |                                    |
   +-----------------------------------+-------------------------------------+------------------------------------+


Cinder supported operations
===========================

Volume replication support
--------------------------

Configure a single replication target
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Configure an SRDF group between the chosen source and target
   arrays for the PowerMax Cinder driver to use. The source array must
   correspond with the ``powermax_array`` entry in ``cinder.conf``.
#. Select both the director and the ports for the SRDF emulation to use on
   both sides. Bear in mind that network topology is important when choosing
   director endpoints. Supported modes are ``Synchronous``, ``Asynchronous``,
   and ``Metro``.

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
      and restart the Cinder volume service.

   .. note::

      If you are setting up an SRDF/Metro configuration, it is recommended that
      you configure a Witness or vWitness for bias management. Please see the
      `SRDF Metro Overview & Best Practices`_ guide for more information.

   .. note::
      The PowerMax Cinder drivers do not support Cascaded SRDF.

#. Enable replication in ``/etc/cinder/cinder.conf``.
   To enable the replication functionality in PowerMax Cinder driver, it is
   necessary to create a replication volume-type. The corresponding
   back-end stanza in ``cinder.conf`` for this volume-type must then
   include a ``replication_device`` parameter. This parameter defines a
   single replication target array and takes the form of a list of key
   value pairs.

   .. code-block:: console

      enabled_backends = POWERMAX_FC_REPLICATION
      [POWERMAX_FC_REPLICATION]
      volume_driver = cinder.volume.drivers.dell_emc.powermax.fc.PowerMaxFCDriver
      san_ip = 10.10.10.10
      san_login = my_u4v_username
      san_password = my_u4v_password
      powermax_srp = SRP_1
      powermax_array = 000123456789
      powermax_port_groups = [OS-FC-PG]
      volume_backend_name = POWERMAX_FC_REPLICATION
      replication_device = target_device_id:000197811111,
                           remote_port_group:os-failover-pg,
                           remote_pool:SRP_1,
                           rdf_group_label: 28_11_07,
                           mode:Metro,
                           metro_use_bias:False,
                           sync_interval:3,
                           sync_retries:200

   .. note::
      ``replication_device`` key value pairs will need to be on the same
      line (separated by commas) in ``cinder.conf``. They are displayed here on
      separate lines above for improved readability.

   * ``target_device_id`` The unique PowerMax array serial number of the
     target array. For full failover functionality, the source and target
     PowerMax arrays must be discovered and managed by the same U4V server.

   * ``remote_port_group`` The name of a PowerMax port group that has been
     pre-configured to expose volumes managed by this backend in the event
     of a failover. Make sure that this port group contains either all FC or
     all iSCSI port groups (for a given back end), as appropriate for the
     configured driver (iSCSI or FC).

   * ``remote_pool`` The unique pool name for the given target array.

   * ``rdf_group_label`` The name of a PowerMax SRDF group that has been
     pre-configured between the source and target arrays.

   * ``mode`` The SRDF replication mode. Options are ``Synchronous``,
     ``Asynchronous``, and ``Metro``. This defaults to ``Synchronous`` if not
     set.

   * ``metro_use_bias`` Flag to indicate if 'bias' protection should be
     used instead of Witness. This defaults to False.

   * ``sync_interval`` How long in seconds to wait between intervals for SRDF
     sync checks during Cinder PowerMax SRDF operations. Default is 3 seconds.

   * ``sync_retries`` How many times to retry RDF sync checks during Cinder
     PowerMax SRDF operations. Default is 200 retries.

   * ``allow_extend`` Only applicable to Hybrid arrays or All Flash arrays
     running HyperMax OS (5977). It is a flag for allowing the extension of
     replicated volumes. To extend a volume in an SRDF relationship, this
     relationship must first be broken, the R1 device extended, and a new
     device pair established. If not explicitly set, this flag defaults to
     ``False``.

     .. note::
        As the SRDF link must be severed, due caution should be exercised when
        performing this operation. If absolutely necessary, only one source and
        target pair should be extended at a time (only only applicable to
        Hybrid arrays or All Flash arrays with HyperMax OS).


#. Create a ``replication-enabled`` volume type. Once the
   ``replication_device`` parameter has been entered in the PowerMax
   backend entry in the ``cinder.conf``, a corresponding volume type
   needs to be created ``replication_enabled`` property set. See
   above `6. Create volume types`_ for details.

   .. code-block:: console

      # openstack volume type set --property replication_enabled="<is> True" \
                            POWERMAX_FC_REPLICATION

   .. note::
      Service Level and Workload: An attempt will be made to create a storage
      group on the target array with the same service level and workload
      combination as the primary. However, if this combination is unavailable
      on the target (for example, in a situation where the source array is a
      Hybrid, the target array is an All Flash, and an All Flash incompatible
      service level like Bronze is configured), no service level will be
      applied.

Configure multiple replication targets
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Setting multiple replication devices in cinder.conf allows the use of all the
supported replication modes simultaneously. Up to three replication devices
can be set, one for each of the replication modes available. An additional
volume type ``extra spec`` (``storagetype:replication_device_backend_id``) is
then used to determine which replication device should be utilized when
attempting to perform an operation on a volume which is replication enabled.
All details, guidelines and recommendations set out in the
`Configure a single replication target`_ section also apply in a multiple
replication device scenario.

Multiple replication targets limitations and restrictions:
    #. There can only be one of each replication mode present across all of the
       replication devices set in ``cinder.conf``.
    #. Details for ``target_device_id``, ``remote_port_group`` and
       ``remote_pool`` should be identical across replication devices.
    #. The ``backend_id`` and ``rdf_group_label`` values must be unique across
       all replication devices.

Adding additional ``replication_device`` to cinder.conf:
    #. Open ``cinder.conf`` for editing
    #. If a replication device is already present, add the ``backend_id`` key
       with a value of ``backend_id_legacy_rep``. If this key is already
       defined, it's value must be updated to ``backend_id_legacy_rep``.
    #. Add the additional replication devices to the backend stanza. Any
       additional replication devices must have a ``backend_id`` key set. The
       value of these must ``not`` be ``backend_id_legacy_rep``.

Example existing backend stanza pre-multiple replication:

.. code-block:: console

   enabled_backends = POWERMAX_FC_REPLICATION

   [POWERMAX_FC_REPLICATION]
   volume_driver = cinder.volume.drivers.dell_emc.powermax.fc.PowerMaxFCDriver
   san_ip = 10.10.10.10
   san_login = my_u4v_username
   san_password = my_u4v_password
   powermax_srp = SRP_1
   powermax_array = 000123456789
   powermax_port_groups = [OS-FC-PG]
   volume_backend_name = POWERMAX_FC_REPLICATION
   replication_device = backend_id:id,
                        target_device_id:000197811111,
                        remote_port_group:os-failover-pg,
                        remote_pool:SRP_1,
                        rdf_group_label: 28_11_07,
                        mode:Metro,
                        metro_use_bias:False,
                        sync_interval:3,
                        sync_retries:200

Example updated backend stanza:

.. code-block:: console

   enabled_backends = POWERMAX_FC_REPLICATION

   [POWERMAX_FC_REPLICATION]
   volume_driver = cinder.volume.drivers.dell_emc.powermax.fc.PowerMaxFCDriver
   san_ip = 10.10.10.10
   san_login = my_u4v_username
   san_password = my_u4v_password
   powermax_srp = SRP_1
   powermax_array = 000123456789
   powermax_port_groups = [OS-FC-PG]
   volume_backend_name = POWERMAX_FC_REPLICATION
   replication_device = backend_id:backend_id_legacy_rep
                        target_device_id:000197811111,
                        remote_port_group:os-failover-pg,
                        remote_pool:SRP_1,
                        rdf_group_label: 28_11_07,
                        mode:Metro,
                        metro_use_bias:False,
                        sync_interval:3,
                        sync_retries:200
   replication_device = backend_id:sync-rep-id
                        target_device_id:000197811111,
                        remote_port_group:os-failover-pg,
                        remote_pool:SRP_1,
                        rdf_group_label: 29_12_08,
                        mode:Synchronous,
                        sync_interval:3,
                        sync_retries:200
   replication_device = backend_id:async-rep-id
                        target_device_id:000197811111,
                        remote_port_group:os-failover-pg,
                        remote_pool:SRP_1,
                        rdf_group_label: 30_13_09,
                        mode:Asynchronous,
                        sync_interval:3,
                        sync_retries:200

.. note::

    For environments without existing replication devices. The
    ``backend_id`` values can be set to any value for all replication devices.
    The ``backend_id_legacy_rep`` value is only needed when updating a legacy
    system with an existing replication device to use multiple replication
    devices.

The additional replication devices defined in ``cinder.conf`` will be detected
after restarting the cinder volume service.

To specify which ``replication_device`` a volume type should use an additional
property named ``storagetype:replication_device_backend_id`` must be added to
the extra specs of the volume type. The id value assigned to the
``storagetype:replication_device_backend_id`` key in the volume type must
match the ``backend_id`` assigned to the ``replication_device`` in
``cinder.conf``.

.. code-block:: console

  # openstack volume type set \
  --property storagetype:replication_device_backend_id="<id>" \
  <VOLUME_TYPE>

.. note::

    Specifying which replication device to use is done in addition to the
    basic replication setup for a volume type seen in
    `Configure a single replication target`_

.. note::

    In a legacy system where volume types are present that were replication
    enabled before adding multiple replication devices, the
    ``storagetype:replication_device_backend_id`` should be omitted from any
    volume type that does/will use the legacy ``replication_device`` i.e.
    when ``storagetype:replication_device_backend_id`` is omitted the
    replication_device with a ``backend_id`` of ``backend_id_legacy_rep``
    will be used.

Volume replication interoperability with other features
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Most features are supported, except for the following:

* Replication Group operations are available for volumes in Synchronous mode
  only.

* The Ussuri release of OpenStack supports retyping in-use volumes to and from
  replication enabled volume types with limited exception of volumes with
  Metro replication enabled. To retype to a volume-type that is Metro enabled
  the volume **must** first be detached then retyped. The reason for this is
  so the paths from the Nova instance to the Metro R1 & R2 volumes must be
  initialised, this is not possible on the R2 device whilst a volume is
  attached.

* The image volume cache functionality is supported (enabled by setting
  ``image_volume_cache_enabled = True``), but one of two actions must be taken
  when creating the cached volume:

  * The first boot volume created on a backend (which will trigger the
    cached volume to be created) should be the smallest necessary size.
    For example, if the minimum size disk to hold an image is 5GB, create
    the first boot volume as 5GB. All subsequent boot volumes are extended
    to the user specific size.
  * Alternatively, ensure that the ``allow_extend`` option in the
    ``replication_device parameter`` is set to ``True``. This is only
    applicable to Hybrid arrays or All Flash array with HyperMax OS.


Failover host
~~~~~~~~~~~~~

.. note::

   Failover and failback operations are not applicable in Metro
   configurations.

In the event of a disaster, or where there is required downtime, upgrade
of the primary array for example, the administrator can issue the failover
host command to failover to the configured target:

.. code-block:: console

   # cinder failover-host cinder_host@POWERMAX_FC_REPLICATION

.. note::

    In cases where multiple replication devices are enabled, a backend_id must
    be specified during initial failover. This can be achieved by appending
    ``--backend_id <backend_id>`` to the failover command above. The backend_id
    specified must match one of the backend_ids specified in ``cinder.conf's``
    ``replication_device's``.

After issuing ``cinder failover-host`` Cinder will set the R2 array as the
target array for Cinder, however, to get existing instances to use this new
array and paths to volumes it is necessary to first shelve Nova instances and
then unshelve them, this will effectively restart the Nova instance and
re-establish data paths between Nova instances and the volumes on the R2 array.

.. code-block:: console

   # nova shelve <server>
   # nova unshelve [--availability-zone <availability_zone>] <server>

When a host is in failover mode performing normal volume or snapshot
provisioning will not be possible, failover host mode simply provides access
to replicated volumes to minimise environment down-time. The primary objective
whilst in failover mode should be to get the R1 array back online.  When the
primary array becomes available again, you can initiate a fail-back using the
same failover command and specifying ``--backend_id default``:

.. code-block:: console

   # cinder failover-host cinder_host@POWERMAX_FC_REPLICATION --backend_id default

After issuing the failover command to revert to the default backend host it is
necessary to re-issue the Nova shelve and unshelve commands to restore the
data paths between Nova instances and their corresponding back end volumes.
Once reverted to the default backend volume and snapshot provisioning
operations can continue as normal.

Asynchronous and metro replication management groups
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Asynchronous and metro volumes in an RDF session, i.e. belonging to an SRDF
group, must be managed together for RDF operations (although there is a
``consistency exempt`` option for creating and deleting pairs in an Async
group). To facilitate this management, we create an internal RDF management
storage group on the backend. This RDF management storage group will use the
following naming convention:

.. code-block:: text

   OS-[rdf_group_label]-[replication_mode]-rdf-sg

It is crucial for correct management that the volumes in this storage group
directly correspond to the volumes in the RDF group. For this reason, it is
imperative that the RDF group specified in the ``cinder.conf`` is for the
exclusive use by this Cinder backend. If there are any issues with the state
of your RDF enabled volumes prior to performing additional operations in Cinder
you will be notified in the Cinder volume logs.


Metro support
~~~~~~~~~~~~~

SRDF/Metro is a high availability solution. It works by masking both sides of
the RDF relationship to the host, and presenting all paths to the host,
appearing that they all point to the one device. In order to do this,
there needs to be multi-path software running to manage writing to the
multiple paths.

.. note::

   The metro issue around formatting volumes when they are added to existing
   metro RDF groups has been fixed in Unisphere for PowerMax 9.1, however, it
   has only been addressed on arrays with PowerMax OS and will not be
   available on arrays running a HyperMax OS.


Volume retype - storage assisted volume migration
--------------------------------------------------

Volume retype with storage assisted migration is supported now for
PowerMax arrays. Cinder requires that for storage assisted migration, a
volume cannot be retyped across backends. For using storage assisted volume
retype, follow these steps:

.. note::

   The Ussuri release of OpenStack supports retyping in-use volumes to and from
   replication enabled volume types with limited exception of volumes with
   Metro replication enabled. To retype to a volume-type that is Metro enabled
   the volume **must** first be detached then retyped. The reason for this is
   so the paths from the instance to the Metro R1 & R2 volumes must be
   initialised, this is not possible on the R2 device whilst a volume is
   attached.

.. note::

   When multiple replication devices are configured. If retyping from one
   replication mode to another the R1 device ID is preserved and a new
   R2 side device is created. As a result, the device ID on the R2 array
   may be different after the retype operation has completed.

.. note::

   Retyping an in-use volume to a metro enabled volume type is not currently
   supported via storage-assisted migration. This retype can still be
   performed using host-assisted migration by setting the migration-policy
   to ``on-demand``.

   .. code-block:: console

      cinder retype --migration-policy on-demand <volume> <volume-type>

#. For migrating a volume from one Service Level or Workload combination to
   another, use volume retype with the migration-policy to on-demand. The
   target volume type should have the same volume_backend_name configured and
   should have the desired pool_name to which you are trying to retype to
   (please refer to `6. Create volume types`_ for details).

   .. code-block:: console

      $ cinder retype --migration-policy on-demand <volume> <volume-type>


Generic volume group support
----------------------------

Generic volume group operations are performed through the CLI using API
version 3.1x of the Cinder API. Generic volume groups are multi-purpose
groups which can be used for various features. The PowerMax driver supports
consistent group snapshots and replication groups. Consistent group
snapshots allows the user to take group snapshots which are consistent based
on the group specs. Replication groups allow for tenant facing APIs to enable
and disable replication, and to failover and failback, a group of volumes.
Generic volume groups have replaced the deprecated consistency groups.

Consistent group snapshot
~~~~~~~~~~~~~~~~~~~~~~~~~

To create a consistent group snapshot, set a group-spec, having the key
``consistent_group_snapshot_enabled`` set to ``<is> True`` on the group.

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-type-key GROUP_TYPE set consistent_group_snapshot_enabled="<is> True"

Similarly the same key should be set on any volume type which is specified
while creating the group.

.. code-block:: console

   # openstack volume type set --property replication_enabled="<is> True" /
                           POWERMAX_REPLICATION

If this key is not set on the group-spec or volume type, then the generic
volume group will be created/managed by Cinder (not the PowerMax driver).

.. note::

   The consistent group snapshot should not be confused with the PowerMax
   consistency group which is an SRDF construct.

Replication groups
~~~~~~~~~~~~~~~~~~

As with Consistent group snapshot ``consistent_group_snapshot_enabled`` should
be set to true on the group and the volume type for replication groups.
Only Synchronous replication is supported for use with Replication Groups.
When a volume is created into a replication group, replication is on by
default. The ``disable_replication`` api suspends I/O traffic on the devices,
but does NOT remove replication for the group. The ``enable_replication`` api
resumes I/O traffic on the RDF links. The ``failover_group`` api allows a group
to be failed over and back without failing over the entire host. See below for
usage.

.. note::

   A generic volume group can be both consistent group snapshot enabled and
   consistent group replication enabled.

Storage group names
~~~~~~~~~~~~~~~~~~~

Storage groups are created on the PowerMax as a result of creation of generic
volume groups. These storage groups follow a different naming convention
and are of the following format depending upon whether the groups have a
name.

.. code-block:: text

   TruncatedGroupName_GroupUUID or GroupUUID

Group type, group, and group snapshot operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Please refer to the official OpenStack `block-storage groups`_ documentation
for the most up to date group operations

Group replication operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Generic volume group operations no longer require the user to specify the
Cinder CLI version, however, performing generic volume group replication
operations still require this setting. When running generic volume group
commands set the value ``--os-volume-api-version`` to ``3.38``. These
commands are not listed in the latest Cinder CLI documentation so will
remain here until added to the latest Cinder CLI version or deprecated
from Cinder.


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


Manage and unmanage Volumes
---------------------------

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

- The volume cannot be a SnapVX target


For a volume to exist in a Cinder managed pool, it must reside in the same
Storage Resource Pool (SRP) as the backend which is configured for use in
OpenStack. Specifying the pool correctly can be entered manually as it follows
the same format:

.. code-block:: console

   Pool format: <service_level>+<srp>+<array_id>
   Pool example: Diamond+SRP_1+111111111111


.. list-table:: Pool values
   :header-rows: 1

   * - Key
     - Value
   * - ``service_level``
     - The service level of the volume to be managed
   * - ``srp``
     - The Storage Resource Pool configured for use by the backend
   * - ``array_id``
     - The PowerMax serial number (12 digit numerical)


Manage volumes
~~~~~~~~~~~~~~

With your pool name defined you can now manage the volume into OpenStack, this
is possible with the CLI command ``cinder manage``. The ``bootable`` parameter
is optional in the command, if the volume to be managed into OpenStack is not
bootable leave this parameter out. OpenStack will also determine the size of
the value when it is managed so there is no need to specify the volume size.

Command format:

.. code-block:: console

   $ cinder manage --name <new_volume_name> --volume-type <powermax_vol_type> \
     --availability-zone <av_zone> <--bootable> <host> <identifier>

Command Example:

.. code-block:: console

   $ cinder manage --name powermax_managed_volume --volume-type POWERMAX_ISCSI_DIAMOND \
     --availability-zone nova demo@POWERMAX_ISCSI_DIAMOND#Diamond+SRP_1+111111111111 031D8

After the above command has been run, the volume will be available for use in
the same way as any other OpenStack PowerMax volume.

.. note::

   An unmanaged volume with a prefix of ``OS-`` in its identifier name cannot
   be managed into OpenStack, as this is a reserved keyword for managed
   volumes. If the identifier name has this prefix, an exception will be thrown
   by the PowerMax driver on a manage operation.


Managing volumes with replication enabled
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Whilst it is not possible to manage volumes into OpenStack that are part of a
SRDF relationship, it is possible to manage a volume into OpenStack and
enable replication at the same time. This is done by having a replication
enabled PowerMax volume type (for more information see section Volume
Replication) during the manage volume process you specify the replication
volume type as the chosen volume type. Once managed, replication will be
enabled for that volume.

.. note::

   It is not possible to manage into OpenStack SnapVX linked target volumes,
   only volumes which are a SnapVX source are permitted. We do not want a
   scenario where a snapshot source can exist outside of OpenStack management.


Unmanage volume
~~~~~~~~~~~~~~~

Unmanaging a volume is not the same as deleting a volume. When a volume is
deleted from OpenStack, it is also deleted from the PowerMax at the same time.
Unmanaging a volume is the process whereby a volume is removed from OpenStack
but it remains for further use on the PowerMax. The volume can also be managed
back into OpenStack at a later date using the process discussed in the
previous section. Unmanaging volume is carried out using the Cinder unmanage
CLI command:

Command format:

.. code-block:: console

   $ cinder unmanage <volume_name/volume_id>

Command example:

.. code-block:: console

   $ cinder unmanage powermax_test_vol

Once unmanaged from OpenStack, the volume can still be retrieved using its
device ID or OpenStack volume ID. Within Unisphere you will also notice that
the ``OS-`` prefix has been removed, this is another visual indication that
the volume is no longer managed by OpenStack.


Manage/unmanage snapshots
-------------------------

Users can manage PowerMax SnapVX snapshots into OpenStack if the source volume
already exists in Cinder. Similarly, users will be able to unmanage OpenStack
snapshots to remove them from Cinder but keep them on the storage backend.

Set-up, restrictions and requirements:

#. No additional settings or configuration is required to support this
   functionality.

#. Manage/Unmanage snapshots requires SnapVX functionality support on PowerMax.

#. Manage/Unmanage Snapshots in OpenStack Cinder is only supported at present
   through Cinder CLI commands.

#. It is only possible to manage or unmanage one snapshot at a time in Cinder.

Manage SnapVX snapshot
~~~~~~~~~~~~~~~~~~~~~~

It is possible to manage PowerMax SnapVX snapshots into OpenStack, where the
source volume from which the snapshot is taken already exists in, and is
managed by OpenStack Cinder. The source volume may have been created in
OpenStack Cinder, or it may have been managed in to OpenStack Cinder also.
With the support of managing SnapVX snapshots included in OpenStack Queens,
the restriction around managing SnapVX source volumes has been removed.

.. note::

   It is not possible to manage into OpenStack SnapVX linked target volumes,
   only volumes which are a SnapVX source are permitted. We do not want a
   scenario where a snapshot source can exist outside of OpenStack management.


Requirements/restrictions:

#. The SnapVX source volume must be present in and managed by Cinder.

#. The SnapVX snapshot name must not begin with ``OS-``.

#. The SnapVX snapshot source volume must not be in a failed-over state.

#. Managing a SnapVX snapshot will only be allowed if the snapshot has no
   linked target volumes.


Command structure:

#. Identify your SnapVX snapshot for management on the PowerMax, note the name.

#. Ensure the source volume is already managed into OpenStack Cinder, note
   the device ID.

#. Using the Cinder CLI, use the following command structure to manage a
   Snapshot into OpenStack Cinder:


.. code-block:: console

   $ cinder snapshot-manage --id-type source-name
                            [--name <name>]
                            [--description <description>]
                            [--metadata [<key=value> [<key=value> ...]]]
                            <volume name/id> <identifier>

Positional arguments:

- ``<volume name/id>`` Source OpenStack volume name

- ``<identifier>`` Name of existing snapshot on PowerMax backend

Optional arguments:

- ``--name <name>`` Snapshot name (Default=``None``)

- ``--description <description>`` Snapshot description (Default=``None``)

- ``--metadata [<key=value> [<key=value> ...]]`` Metadata ``key=value`` pairs
  (Default=``None``)

Example:

.. code-block:: console

   $ cinder snapshot-manage --name SnapshotManaged \
                            --description "Managed Queens Feb18" \
                            powermax-vol-1 PowerMaxSnapshot

Where:

- The name in OpenStack after managing the SnapVX snapshot will be
  ``SnapshotManaged``.

- The snapshot will have the description ``Managed Queens Feb18``.

- The Cinder volume name is ``powermax-vol-1``.

- The name of the SnapVX snapshot on the PowerMax backend is
  ``PowerMaxSnapshot``.

Outcome:

After the process of managing the Snapshot has completed, the SnapVX snapshot
on the PowerMax backend will be prefixed by the letters ``OS-``, leaving the
snapshot in this example named ``OS-PowerMaxSnapshot``. The associated snapshot
managed by Cinder will be present for use under the name ``SnapshotManaged``.


Unmanage cinder snapshot
~~~~~~~~~~~~~~~~~~~~~~~~

Unmanaging a snapshot in Cinder is the process whereby the snapshot is removed
from and no longer managed by Cinder, but it still exists on the storage
backend. Unmanaging a SnapVX snapshot in OpenStack Cinder follows this
behaviour, whereby after unmanaging a PowerMax SnapVX snapshot from Cinder, the
snapshot is removed from OpenStack but is still present for use on the PowerMax
backend.

Requirements/Restrictions:

- The SnapVX source volume must not be in a failed over state.

Command Structure:

Identify the SnapVX snapshot you want to unmanage from OpenStack Cinder, note
the snapshot name or ID as specified by Cinder. Using the Cinder CLI use the
following command structure to unmanage the SnapVX snapshot from Cinder:

.. code-block:: console

   $ cinder snapshot-unmanage <snapshot>

Positional arguments:

- ``<snapshot>`` Cinder snapshot name or ID.

Example:

.. code-block:: console

   $ cinder snapshot-unmanage SnapshotManaged

Where:

- The SnapVX snapshot name in OpenStack Cinder is SnapshotManaged.

After the process of unmanaging the SnapVX snapshot in Cinder, the snapshot on
the PowerMax backend will have the ``OS-`` prefix removed to indicate it is no
longer OpenStack managed. In the example above, the snapshot after unmanaging
from OpenStack will be named ``PowerMaxSnapshot`` on the storage backend.

List manageable volumes and snapshots
-------------------------------------

Manageable volumes
~~~~~~~~~~~~~~~~~~

Volumes that can be managed by and imported into Openstack.

List manageable volume is filtered by:

- Volume size should be 1026MB or greater (1GB PowerMax Cinder Vol = 1026 MB)
- Volume size should be a whole integer GB capacity
- Volume should not be a part of masking view.
- Volume status should be ``Ready``
- Volume service state should be ``Normal``
- Volume emulation type should be ``FBA``
- Volume configuration should be ``TDEV``
- Volume should not be a system resource.
- Volume should not be ``private``
- Volume should not be ``encapsulated``
- Volume should not be ``reserved``
- Volume should not be a part of an RDF session
- Volume should not be a SnapVX Target
- Volume identifier should not begin with ``OS-``.

Manageable snaphots
~~~~~~~~~~~~~~~~~~~

Snapshots that can be managed by and imported into Openstack

List manageable snapshots is filtered by:

- The source volume should be marked as SnapVX source.
- The source volume should be 1026MB or greater
- The source volume should be a whole integer GB capacity.
- The source volume emulation type should be ``FBA``.
- The source volume configuration should be ``TDEV``.
- The source volume should not be ``private``.
- The source volume should be not be a system resource.
- The snapshot identifier should not start with ``OS-`` or ``temp-``.
- The snapshot should not be expired.
- The snapshot generation number should npt be greater than 0.

.. note::

   There is some delay in the syncing of the Unisphere for PowerMax database
   when the state/properties of a volume is modified using ``symcli``.  To
   prevent this it is preferable to modify state/properties of volumes within
   Unisphere.


Cinder backup support
---------------------

PowerMax Cinder driver support Cinder backup functionality. For further
information on setup, configuration and usage please see the official
OpenStack `volume backup`_ documentation and related `volume backup CLI`_
guide.

Upgrading from SMI-S based driver to REST API based driver
==========================================================

Seamless upgrades from an SMI-S based driver to REST API based driver,
following the setup instructions above, are supported with a few exceptions:

#. Seamless upgrade from SMI-S(Ocata and earlier) to REST(Pike and later)
   is now available on all functionality including Live Migration.

#. Consistency groups are deprecated in Pike. Generic Volume Groups are
   supported from Pike onwards.


.. Document Hyperlinks
.. _Dell EMC Support: https://www.dell.com/support
.. _Openstack CLI: https://docs.openstack.org/cinder/latest/cli/cli-manage-volumes.html#volume-types
.. _over-subscription documentation: https://docs.openstack.org/cinder/latest/admin/blockstorage-over-subscription.html
.. _configuring migrations: https://docs.openstack.org/nova/latest/admin/configuring-migrations.html
.. _live migration usage: https://docs.openstack.org/nova/latest/admin/live-migration-usage.html
.. _Ubuntu NFS Documentation: https://help.ubuntu.com/lts/serverguide/network-file-system.html
.. _multi-attach documentation: https://docs.openstack.org/cinder/latest/admin/blockstorage-volume-multiattach.html
.. _Data at Rest Encryption: https://www.dellemc.com/resources/en-us/asset/white-papers/products/storage/h13936-dell-emc-powermax-vmax-all-flash-data-rest-encryption.pdf
.. _official Barbican documentation: https://docs.openstack.org/cinder/latest/configuration/block-storage/volume-encryption.html
.. _SRDF Metro Overview & Best Practices: https://www.emc.com/collateral/technical-documentation/h14556-vmax3-srdf-metro-overview-and-best-practices-tech-note.pdf
.. _block-storage groups: https://docs.openstack.org/cinder/latest/admin/blockstorage-groups.html
.. _volume backup: https://docs.openstack.org/cinder/latest/configuration/block-storage/backup-drivers.html
.. _volume backup CLI: https://docs.openstack.org/python-openstackclient/latest/cli/command-objects/volume-backup.html
.. _PyU4V: https://pyu4v.readthedocs.io/en/latest/
